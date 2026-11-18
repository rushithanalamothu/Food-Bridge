"""Custom-format backup and isolated restore verification through Docker Compose.

Restore never overwrites an existing database. Keep dumps private and encrypt off-host copies.
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from uuid import uuid4


def verify_restore(compose, archive, database):
    if not re.fullmatch(r"foodbridge_restore_[a-z0-9_]{1,32}", database):
        raise ValueError("Restore target must be an isolated foodbridge_restore_* database")
    base = [*compose, "exec", "-T", "db"]
    subprocess.run(
        [*base, "createdb", "-U", "foodbridge", database], check=True, capture_output=True
    )
    # A failure leaves the isolated target for inspection; it never cleans the live DB.
    with Path(archive).open("rb") as source:
        subprocess.run(
            [
                *base,
                "pg_restore",
                "-U",
                "foodbridge",
                "--dbname",
                database,
                "--exit-on-error",
                "--no-owner",
            ],
            stdin=source,
            check=True,
            capture_output=True,
        )
    query = """
    SELECT json_build_object(
      'migration',(SELECT version_num FROM alembic_version),
      'donations',(SELECT count(*) FROM donations),
      'active_reservations',(SELECT count(*) FROM reservations WHERE status='active'),
      'impact_rows',(SELECT count(*) FROM delivery_impact),
      'duplicate_active_reservations',(SELECT count(*) FROM
        (SELECT donation_id FROM reservations WHERE status='active'
         GROUP BY donation_id HAVING count(*)>1) x));
    """

    result = subprocess.run(
        [*base, "psql", "-U", "foodbridge", "-d", database, "-At", "-c", query],
        check=True,
        capture_output=True,
        text=True,
    )
    restored = json.loads(result.stdout)
    source_counts = subprocess.run(
        [*base, "psql", "-U", "foodbridge", "-d", "foodbridge", "-At", "-c", query],
        check=True,
        capture_output=True,
        text=True,
    )
    original = json.loads(source_counts.stdout)
    if restored != original:
        raise ValueError(
            "Restore/source counts differ. Quiesce writes and repeat for comparable snapshots."
        )
    if restored["duplicate_active_reservations"]:
        raise ValueError("Restored reservation invariant failed")
    return restored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose", action="append", required=True, help="Compose file; repeat for overrides"
    )
    parser.add_argument("--project")
    parser.add_argument("--env-file")
    parser.add_argument("action", choices=["backup", "verify-restore"])
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--database", default="foodbridge_restore_" + uuid4().hex[:12])
    args = parser.parse_args()
    compose = ["docker", "compose"]
    if args.env_file:
        compose += ["--env-file", args.env_file]
    if args.project:
        compose += ["-p", args.project]
    for file in args.compose:
        compose += ["-f", file]
    if args.action == "backup":
        args.archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # O_EXCL prevents accidentally replacing a previous backup.
        with args.archive.open("xb") as target:
            args.archive.chmod(0o600)
            subprocess.run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "db",
                    "pg_dump",
                    "-U",
                    "foodbridge",
                    "-d",
                    "foodbridge",
                    "-Fc",
                    "--no-owner",
                ],
                stdout=target,
                check=True,
            )
        print(
            json.dumps(
                {
                    "archive": str(args.archive),
                    "sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
                }
            )
        )
    else:
        counts = verify_restore(compose, args.archive, args.database)
        print(json.dumps({"isolated_database": args.database, "verified": True, **counts}))


if __name__ == "__main__":
    main()
