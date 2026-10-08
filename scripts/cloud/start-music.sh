#!/usr/bin/env bash
# Run the existing music-dev sidecar and pinned upstream entirely in this VM.
set -euo pipefail
export PATH="${HOME}/.local/bin:$PATH"
cd "$(dirname "$0")/../.."
source_dir="$PWD/.wavecast-data/cloud/music-dev"
if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
  echo 'Docker daemon is unavailable; diagnose cloud Docker before live generation.' >&2
  exit 1
fi
if [[ ! -d "$source_dir/.git" ]]; then
  mkdir -p "$(dirname "$source_dir")"
  git clone https://github.com/ZakuZakuu/wavecast-music-dev.git "$source_dir"
fi
# Do not silently pull: record the sidecar revision for this experiment.
printf 'Music-dev revision: '
git -C "$source_dir" rev-parse HEAD
if docker container inspect wavecast-cloud-netease >/dev/null 2>&1; then
  echo 'Existing wavecast-cloud-netease container found; check it before restarting.' >&2
  exit 1
fi
docker build -f "$source_dir/Dockerfile.upstream" -t wavecast-cloud-netease "$source_dir"
# Host 3100 avoids collision with the Next frontend at 3000.
docker run --rm -d --name wavecast-cloud-netease \
  -p 127.0.0.1:3100:3000 wavecast-cloud-netease >/dev/null
export NETEASE_UPSTREAM_BASE_URL=http://127.0.0.1:3100
export NETEASE_UPSTREAM_TIMEOUT_SECONDS=10
unset NETEASE_UPSTREAM_BEARER_TOKEN
# Native sidecar can reach the host-mapped upstream via loopback.
uv --directory "$source_dir" sync --locked --all-groups
exec uv --directory "$source_dir" run uvicorn netease_sidecar.app:app \
  --host 127.0.0.1 --port 3101
