#!/usr/bin/env bash
# Prepare a local OpenStreetMap extract for the optional OSRM Compose service.
set -euo pipefail

if [[ $# != 1 || ! -f "$1" || "$1" != *.osm.pbf ]]; then
  echo 'Usage: scripts/prepare_osrm.sh /path/to/region.osm.pbf' >&2
  exit 2
fi
command -v docker >/dev/null || { echo 'Docker is required.' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
directory="$root/data/osrm"
mkdir -p "$directory"
if compgen -G "$directory/region.osrm*" >/dev/null || [[ -f "$directory/region.osm.pbf" ]]; then
  echo 'OSRM data already exists. Use a fresh checkout or move it aside before preparing another extract.' >&2
  exit 2
fi

cp "$1" "$directory/region.osm.pbf"
image="$(docker compose --profile routing config --format json | uv run python -c 'import json, sys; print(json.load(sys.stdin)["services"]["routing"]["image"])')"
docker run --rm -v "$directory:/data" "$image" osrm-extract -p /opt/car.lua /data/region.osm.pbf
docker run --rm -v "$directory:/data" "$image" osrm-partition /data/region.osrm
docker run --rm -v "$directory:/data" "$image" osrm-customize /data/region.osrm
if [[ ! -f "$directory/region.osrm.partition" || ! -f "$directory/region.osrm.mldgr" ]]; then
  echo 'OSRM preprocessing did not produce an MLD route graph.' >&2
  exit 1
fi
image_id="$(docker image inspect "$image" --format '{{.Id}}')"
uv run python - "$directory/region.osm.pbf" "$directory/manifest.json" "$image" "$image_id" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

source, destination, image, image_id = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
with source.open('rb') as file:
    digest = hashlib.file_digest(file, 'sha256').hexdigest()
destination.write_text(json.dumps({
    'source_filename': source.name,
    'source_sha256': digest,
    'routing_image': image,
    'routing_image_id': image_id,
    'profile': 'car',
    'algorithm': 'mld',
}, indent=2) + '\n')
print(f'OSRM dataset ready: {destination} (SHA-256 {digest})')
PY
