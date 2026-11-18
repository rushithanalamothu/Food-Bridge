# Synthetic data

`fixtures/` is for small reviewed regression scenarios. `generated/` contains local generated datasets and is ignored except its README. Canonical valid wire examples live in `contracts/examples/`, not in duplicated copies here.

Run `uv run python scripts/generate_synthetic.py` from root. It writes a deterministic file with 10 donors, 6 recipients, 5 drivers and 20 donations; base clock and seed are explicit. The records are synthetic and do not identify real organizations. A separate [local matching seed](../docs/features/live-matching.md) inserts a donor, two recipients and one driver without loading donations or overwriting capacities; the full F05 fixture loader remains outstanding. See `docs/testing.md` for evaluation requirements.
