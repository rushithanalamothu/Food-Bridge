"""Deterministic file-only fixture generator. Does not write to a database or send tasks."""

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from foodbridge.domain.contracts import DonationRead, RecipientProfile

ROOT = Path(__file__).resolve().parents[1]


def identifier(kind: str, index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"foodbridge/{kind}/{index}"))


def generate(seed: int, base_time: datetime) -> dict:
    if base_time.tzinfo is None:
        raise ValueError("base_time must have a timezone")
    rng = random.Random(seed)
    example = json.loads((ROOT / "contracts/examples/donation-input.json").read_text())
    donors = [
        {"id": identifier("donor", i), "name": f"Synthetic Kitchen {i + 1}"} for i in range(10)
    ]
    recipients = []
    for i in range(6):
        recipients.append(
            RecipientProfile(
                organization_id=identifier("recipient", i),
                location={
                    **example["pickup_location"],
                    "latitude": 37.32 + rng.random() * 0.08,
                    "longitude": -121.94 + rng.random() * 0.08,
                },
                accepted_categories=["prepared_meals", "produce", "bakery"],
                accepted_storage=["ambient", "chilled"],
                available_capacity_kg_by_storage={
                    "ambient": rng.choice([5, 10, 20, 40]),
                    "chilled": rng.choice([5, 10, 20, 40]),
                },
                rejected_allergens=["peanut"] if i % 2 else [],
                receiving_window={"start": base_time, "end": base_time + timedelta(hours=8)},
                version=1,
            ).model_dump(mode="json")
        )
    donations = []
    for i in range(20):
        value = {
            **example,
            "id": identifier("donation", i),
            "donor_organization_id": donors[i % 10]["id"],
            "status": "submitted",
            "version": 1,
            "created_at": base_time,
            "quantity_kg": rng.choice([5, 10, 20]),
            "pickup_window": {
                "start": base_time + timedelta(minutes=15),
                "end": base_time + timedelta(hours=2 + i % 3),
            },
            "safe_use_by": base_time + timedelta(hours=5 + i % 3),
        }
        donations.append(DonationRead.model_validate(value).model_dump(mode="json"))
    return {
        "metadata": {"seed": seed, "base_time": base_time.isoformat(), "synthetic": True},
        "donors": donors,
        "recipients": recipients,
        "drivers": [
            {"id": identifier("driver", i), "name": f"Synthetic Driver {i + 1}"} for i in range(5)
        ],
        "donations": donations,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--base-time", default="2026-10-30T20:00:00+00:00")
    parser.add_argument("--output", type=Path, default=ROOT / "data/generated/scenario.json")
    args = parser.parse_args()
    data = generate(args.seed, datetime.fromisoformat(args.base_time))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {args.output}: 10 donors, 6 recipients, 5 drivers, 20 donations.")


if __name__ == "__main__":
    main()
