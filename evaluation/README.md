# Matching evaluation — Rushitha

The offline comparison uses `scripts/generate_synthetic.py`'s fixed 10-donor/6-recipient/5-driver/20-donation fixture and explicitly synthetic route lengths. Both strategies run the same intake policy independently, with separate simulated capacity and accepted-allocation ledgers. It reports selections, no matches, allocation kilograms, Jain's index across all six fixture recipients, and local CPU decision timing. The manifest records the dataset hash, seed, base clock, build SHA, policy and ranking versions. Run:

```bash
uv run python -m evaluation.compare --seed 2026 --base-time 2026-10-30T20:00:00+00:00 --output evaluation/results/synthetic-2026.json
```

The ignored result file contains raw per-donation decisions and a separate summary for each strategy. These are **synthetic offline** numbers. There is no OSRM call, network/queue latency, real DB locking, model inference, driver concurrency or pickup/delivery outcome in this replay. An all-recipient fairness index is only a fixture proxy; production fairness needs comparable eligibility cohorts. Never present its CPU timing as submitted-to-offer latency, or its selection count as pickup success. This fixture is too small to claim that either strategy improves outcomes.

For an offline comparison with *real local road routes*, pass `--routing-url
http://127.0.0.1:5000` after preparing the [optional OSRM service](../docs/features/live-matching.md).
Route facts are fetched once and shared by both strategies. The fixture entities, capacity and
acceptance are still synthetic. Route fetch time is separate from CPU decision time; neither
number is submitted-to-offer latency or evidence of successful pickups.

For measured product evaluation, follow [the protocol](../docs/testing.md): run both strategies against independent restored PostgreSQL snapshots, real configured routing, identical workload/clock and monitored workers; collect submitted-to-offer P50/P95, reservations, pickup/delivery, constraints, competing capacity, cohorts and failure/recovery records. Review the raw output before publishing a summary. No production benchmark is claimed here.

The [local serial full-stack harness](../docs/features/live-matching.md#measure-the-local-full-stack-workflow)
records actual worker/API offer timing and scripted delivery on two distinct Compose databases.
It is a repeatable integration measurement, not the independent restored-snapshot, burst-load
or human-outcome evaluation described above.
