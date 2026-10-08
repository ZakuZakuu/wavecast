#!/usr/bin/env bash
# VM provisioning only. No credentials, provider calls or persistent services.
set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg postgresql ca-certificates curl
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
# Install Python into a cached filesystem location; sessions still run uv sync.
export PATH="${HOME}/.local/bin:$PATH"
uv python install 3.12
