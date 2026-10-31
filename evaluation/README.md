# Matching evaluation — Rushitha

Implementation workspace for independent distance-only and multi-criteria scenario runners. There are no measured experiment results yet. See `docs/testing.md` for metric denominators, fairness/cohort definitions, independent state resets and required manifest fields.

Both strategies use the same deterministic eligibility and routing inputs. Never run them sequentially against capacity/history modified by the other. Store raw output under ignored `results/`; commit only reviewed reproducible summaries when actual measurements exist.
