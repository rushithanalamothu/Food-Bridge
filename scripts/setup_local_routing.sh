#!/usr/bin/env bash
# Small real-road dataset covering the synthetic San Jose demo actors.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
if [[ ! -f data/osrm/region.osrm.mldgr || ! -f data/osrm/manifest.json ]]; then
  task_directory="$(mktemp -d)"
  trap 'rm -rf "$task_directory"' EXIT
  source_url='https://download.bbbike.org/osm/bbbike/SanJose/SanJose.osm.pbf'
  curl --fail --location --retry 2 --max-time 300 "$source_url" -o "$task_directory/SanJose.osm.pbf"
  bash scripts/prepare_osrm.sh "$task_directory/SanJose.osm.pbf"
  uv run python - "$source_url" <<'PY'
import json
import sys
from pathlib import Path

path = Path('data/osrm/manifest.json')
manifest = json.loads(path.read_text())
manifest.update(source_url=sys.argv[1], attribution='© OpenStreetMap contributors', license='ODbL 1.0')
path.write_text(json.dumps(manifest, indent=2) + '\n')
PY
fi
docker compose --profile routing up -d routing
binding="$(docker compose --profile routing port routing 5000)"
route_url="http://$binding/route/v1/driving/-121.89,37.332;-121.8881,37.3348?overview=false"
for attempt in {1..20}; do
  if curl --silent --fail --max-time 2 "$route_url" | uv run python -c 'import json,sys; assert json.load(sys.stdin)["code"] == "Ok"' 2>/dev/null; then
    echo 'Local OSRM is ready with real San Jose road routes (OpenStreetMap / ODbL).'
    exit 0
  fi
  sleep 1
done
echo 'OSRM did not become ready or the dataset does not cover the demo coordinates.' >&2
exit 1
