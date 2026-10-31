"""Export deterministic schema artifacts; --check never overwrites files."""

import argparse
import json
from pathlib import Path

from foodbridge.api.main import create_app
from foodbridge.domain.contracts import FoodBridgeContracts

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    artifacts = {
        "contracts/domain.schema.json": FoodBridgeContracts.model_json_schema(),
        "contracts/openapi.json": create_app().openapi(),
    }
    for relative, value in artifacts.items():
        path = ROOT / relative
        content = json.dumps(value, indent=2, sort_keys=True) + "\n"
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Stale contract: {relative}. Run make contracts.")
        else:
            path.write_text(content)


if __name__ == "__main__":
    main()
