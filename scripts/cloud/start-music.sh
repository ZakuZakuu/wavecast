#!/usr/bin/env bash
# Run the existing music-dev sidecar and pinned upstream entirely in this VM.
# Default: upstream runs natively with Node (the Claude cloud proxy CA is not
# trusted inside Docker builds and Docker Hub pulls are rate limited).
# Optional: --docker keeps the original container flow for hosts without a proxy.
set -euo pipefail
export PATH="${HOME}/.local/bin:$PATH"
cd "$(dirname "$0")/../.."
mode=${1:---native}
case "$mode" in
  --native|--docker) ;;
  *) echo 'Usage: bash scripts/cloud/start-music.sh [--native|--docker]' >&2; exit 2 ;;
esac
data_dir="$PWD/.wavecast-data/cloud"
source_dir="$data_dir/music-dev"
upstream_dir="$data_dir/ncm-upstream"
upstream_repo=https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced.git
upstream_commit=a8c781fd64faab17fedfd46e0615a2609307f163
if [[ ! -d "$source_dir/.git" ]]; then
  mkdir -p "$data_dir"
  GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/ZakuZakuu/wavecast-music-dev.git "$source_dir"
fi
# Do not silently pull: record the sidecar revision for this experiment.
printf 'Music-dev revision: '
git -C "$source_dir" rev-parse HEAD

if [[ "$mode" == --docker ]]; then
  if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
    echo 'Docker daemon is unavailable; start dockerd or use --native.' >&2
    exit 1
  fi
  if docker container inspect wavecast-cloud-netease >/dev/null 2>&1; then
    echo 'Existing wavecast-cloud-netease container found; check it before restarting.' >&2
    exit 1
  fi
  docker build -f "$source_dir/Dockerfile.upstream" -t wavecast-cloud-netease "$source_dir"
  # Host 3100 avoids collision with the Next frontend at 3000.
  docker run --rm -d --name wavecast-cloud-netease \
    -p 127.0.0.1:3100:3000 wavecast-cloud-netease >/dev/null
else
  if curl --silent --output /dev/null --max-time 2 http://127.0.0.1:3100/; then
    echo 'Something already listens on 127.0.0.1:3100; check it before restarting.' >&2
    exit 1
  fi
  if [[ ! -d "$upstream_dir/.git" ]]; then
    mkdir -p "$upstream_dir"
    git -C "$upstream_dir" init -q
    git -C "$upstream_dir" remote add origin "$upstream_repo"
  fi
  if [[ "$(git -C "$upstream_dir" rev-parse HEAD 2>/dev/null || true)" != "$upstream_commit" ]]; then
    git -C "$upstream_dir" fetch -q --depth 1 origin "$upstream_commit"
    git -C "$upstream_dir" checkout -q --detach FETCH_HEAD
  fi
  printf 'Upstream revision: '
  git -C "$upstream_dir" rev-parse HEAD
  # Production install without lifecycle scripts (husky is dev-only), as upstream's Dockerfile.
  (cd "$upstream_dir" && npx --yes pnpm@9 install --frozen-lockfile --prod --ignore-scripts)
  # NODE_EXTRA_CA_CERTS lets Node trust the sandbox proxy CA when present.
  ca_bundle=${NODE_EXTRA_CA_CERTS:-/root/.ccr/ca-bundle.crt}
  [[ -f "$ca_bundle" ]] && export NODE_EXTRA_CA_CERTS="$ca_bundle"
  (cd "$upstream_dir" && NODE_ENV=production PORT=3100 HOST=127.0.0.1 \
    nohup node app.js > "$data_dir/ncm-upstream.log" 2>&1 &
    echo $! > "$data_dir/ncm-upstream.pid")
  echo "Upstream log: $data_dir/ncm-upstream.log (pid file ncm-upstream.pid)"
  for _ in $(seq 1 30); do
    curl --silent --output /dev/null --max-time 2 http://127.0.0.1:3100/ && break
    sleep 1
  done
fi
export NETEASE_UPSTREAM_BASE_URL=http://127.0.0.1:3100
export NETEASE_UPSTREAM_TIMEOUT_SECONDS=10
unset NETEASE_UPSTREAM_BEARER_TOKEN
# Native sidecar can reach the host-mapped upstream via loopback.
uv --directory "$source_dir" sync --locked --all-groups
exec uv --directory "$source_dir" run uvicorn netease_sidecar.app:app \
  --host 127.0.0.1 --port 3101
