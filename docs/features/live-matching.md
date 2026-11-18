# Local road-routing matching verification

This is a **local synthetic-actor test with real PostGIS, Redis, worker processes and OSRM road
routes**. It does not provision genuine users or measure pickup rates. Use a fresh local
database or a disposable copy; the seed never clears or overwrites existing records.

## Prepare the map

Download an OpenStreetMap extract that covers San Jose, California, such as
[Geofabrik's Northern California extract](https://download.geofabrik.de/north-america/us/california/norcal.html).
It is a large download and OSRM preprocessing needs additional disk and memory. From the repo
root (adjust the downloaded path):

```sh
bash scripts/prepare_osrm.sh "$HOME/Downloads/norcal-latest.osm.pbf"
make routing-up
curl 'http://127.0.0.1:5000/route/v1/driving/-121.89,37.332;-121.8881,37.3348?overview=false'
```

The response must contain `"code":"Ok"`. The preparation script follows OSRM's car-profile
MLD pipeline (extract, partition, customize). Its route files and map checksum stay ignored in
`data/osrm/`; the optional `routing` Compose service reads those files. It binds port 5000 to
localhost. `FOODBRIDGE_ROUTING_IMAGE` may pin the same image for preparation and serving; the
script reads the resolved Compose image setting. For an updated map, move the old dataset aside
and prepare a new one rather than mixing files. See the [OSRM Docker instructions](https://github.com/Project-OSRM/osrm-backend#using-docker).

## Run one complete local workflow

Set these values in the private root `.env` (keep the default local DB and Redis URLs):

```dotenv
FOODBRIDGE_ENABLE_LOCAL_INTAKE_DEMO=true
FOODBRIDGE_ENABLE_LOCAL_MATCHING_DEMO=true
FOODBRIDGE_ENABLE_LOCAL_WORKFLOW_DEMO=false
FOODBRIDGE_ROUTING_BASE_URL=http://routing:5000
FOODBRIDGE_NOTIFICATION_MODE=sandbox
FOODBRIDGE_AI_PROVIDER=rules
```

`make routing-up` starts OSRM; `make up` builds and starts the backend stack. Then run:

```sh
make up
make seed-matching-demo
make smoke-matching
```

The fixture adds a donor, two verified recipient organizations and one driver with deterministic
IDs and synthetic San Jose coordinates. The driver origin is updated through the authenticated
local-only API immediately before the listing; it expires after five minutes. The two recipient
organizations share a synthetic user; requests choose a recipient with `X-Organization-ID`.
Bearer tokens, when present, are always verified normally. The matching demo flag is rejected
outside `local` and cannot be combined with browser authentication or the synthetic workflow matcher.

The smoke creates a draft, confirms a donation, waits for a persisted offer, checks that the
evaluation and stored route are not synthetic, reserves, accepts the driver assignment, confirms
pickup/delivery and reads a persisted SSE event. Its output includes the donor ID, selected
recipient and road distance. A `NoRoute` response means the map does not cover the fixture
coordinates. Inspect the worker logs and failed workflow state for other failures.

## Compare ranking strategies

With the local OSRM service still running:

```sh
uv run python -m evaluation.compare --routing-url http://127.0.0.1:5000 \
  --seed 2026 --base-time 2026-10-30T20:00:00+00:00 \
  --output evaluation/results/osrm-2026.json
```

Both strategies receive the *same fetched road routes* and independent simulated capacity
ledgers. The result records dataset and route-fact hashes, policy/ranking versions, route fetch
time and CPU decision timing. The 20 donations, recipients and driver origin remain synthetic;
this replay does not include PostGIS queries, API/queue latency, driver races or completed
pickups. To claim product performance, follow the independent database-snapshot and outcome
protocol in [testing](../testing.md). Keep the raw output and map manifest with any reported
figures; the ignored `evaluation/results/` folder is not automatically published.

## Measure the local full-stack workflow

The serial harness creates 20 one-kilogram donations, auto-reserves and confirms each
pickup/delivery, and records the server's stored submission-to-offer timestamps plus a
client-observed latency. It refuses databases containing prior donations and requires a clean
committed tree. Run it once per strategy in **two different Compose projects** so their
PostgreSQL volumes start independently. Stop any earlier default-project stack first:

```sh
docker compose --profile routing down
export COMPOSE_PROJECT_NAME=foodbridge-distance-run1
# Set FOODBRIDGE_MATCHING_ALGORITHM=distance_only in .env
make routing-up
make up
make seed-matching-demo
uv run python -m scripts.benchmark_matching --strategy distance_only \
  --output evaluation/results/distance-run1.json
docker compose --profile routing down

export COMPOSE_PROJECT_NAME=foodbridge-multi-run1
# Set FOODBRIDGE_MATCHING_ALGORITHM=multi_criteria in .env
make routing-up
make up
make seed-matching-demo
uv run python -m scripts.benchmark_matching --strategy multi_criteria \
  --output evaluation/results/multi-run1.json
uv run python -m evaluation.compare_live \
  evaluation/results/distance-run1.json evaluation/results/multi-run1.json
```

`docker compose ... down` retains database volumes; no volume deletion is needed. Use new
project names for repeated independent runs. The comparison rejects a shared project, map
drift, code/config drift and incomplete runs. The timings describe this serial local stack and
scripted acceptance; human acceptance rates, burst throughput and concurrent capacity races
require the wider [evaluation protocol](../testing.md). Keep the two raw JSON files and map
manifest before reporting a comparison.
