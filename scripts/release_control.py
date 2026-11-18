"""Promote/rollback versioned API/worker/frontend images, recording previous references.

Operate on a configured host. DB rollback is deliberately not automatic or destructive.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def image(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]+", value) or ":latest" in value:
        raise ValueError("Use an immutable reviewed image digest or unique release tag")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default="deploy/runtime/runtime.env")
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--backend-image")
    parser.add_argument("--web-image")
    parser.add_argument(
        "--rollback", type=Path, help="Previous release JSON; schema must remain compatible"
    )
    args = parser.parse_args()
    env = Path(args.env_file).resolve()
    # Reuse dotenv parsing without evaluating shell text or printing secrets.
    from dotenv import dotenv_values

    values = dotenv_values(env)
    old = {key: values[key] for key in ("FOODBRIDGE_BACKEND_IMAGE", "FOODBRIDGE_WEB_IMAGE")}
    if args.rollback:
        previous = json.loads(args.rollback.read_text())["previous"]
        selected = {key: image(previous[key]) for key in old}
    else:
        selected = {
            "FOODBRIDGE_BACKEND_IMAGE": image(args.backend_image or ""),
            "FOODBRIDGE_WEB_IMAGE": image(args.web_image or ""),
        }
    lines = env.read_text().splitlines()
    content = (
        "\n".join(
            f"{line.split('=', 1)[0]}='{selected[line.split('=', 1)[0]]}'"
            if line.split("=", 1)[0] in selected
            else line
            for line in lines
        )
        + "\n"
    )
    args.record.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {
        "at": datetime.now(UTC).isoformat(),
        "previous": old,
        "selected": selected,
        "rollback": bool(args.rollback),
        "verified": False,
    }
    # Keep the previous release record even if deployment fails halfway.
    with args.record.open("x") as target:
        json.dump(record, target, indent=2)
    env.write_text(content)
    env.chmod(0o600)
    compose = ["docker", "compose", "--env-file", str(env), "-f", "deploy/compose.production.yml"]
    try:
        subprocess.run([*compose, "pull"], check=True)
        # Migration is additive; rolling back images never automatically downgrades data.
        subprocess.run([*compose, "up", "-d", "db", "redis", "auth-db"], check=True)
        if not args.rollback:
            subprocess.run([*compose, "run", "--rm", "migrate"], check=True)
        if args.rollback:
            # Do not rerun an old image's Alembic against a newer additive schema.
            subprocess.run(
                [
                    *compose,
                    "up",
                    "-d",
                    "--no-deps",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "api",
                    "intake",
                    "matching",
                    "orchestrator",
                    "reservation",
                    "intake-relay",
                    "workflow-runtime",
                    "keycloak",
                    "web",
                    "prometheus",
                ],
                check=True,
            )
        else:
            subprocess.run([*compose, "up", "-d", "--wait", "--wait-timeout", "180"], check=True)
        subprocess.run(
            [
                *compose,
                "exec",
                "-T",
                "api",
                "uv",
                "run",
                "--no-sync",
                "alembic",
                "-c",
                "backend/alembic.ini",
                "current",
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "scripts/smoke_gateway.py",
                "--base-url",
                values["FOODBRIDGE_PUBLIC_URL"],
            ],
            check=True,
        )
        record["gateway_verified"] = True
        record["services_ready"] = True
        record["requires_authenticated_release_smoke"] = True
        # Startup/readiness is intentionally not called complete release verification.
    finally:
        args.record.write_text(json.dumps(record, indent=2) + "\n")
    print(
        "Images started. Run authenticated acceptance smoke and record its result "
        "before promotion is accepted."
    )


if __name__ == "__main__":
    main()
