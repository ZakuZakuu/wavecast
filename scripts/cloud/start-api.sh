#!/usr/bin/env bash
# Dedicated cloud-local database; never accepts a hosted production URL.
set -euo pipefail
export PATH="${HOME}/.local/bin:$PATH"
cd "$(dirname "$0")/../.."
mode=${1:---mock}
no_tts=${2:-}
if [[ -n "$no_tts" && "$no_tts" != --no-tts ]]; then
  echo 'Usage: bash scripts/cloud/start-api.sh --mock|--live [--no-tts]' >&2; exit 2
fi
case "$mode" in
  --mock) export WAVECAST_PROVIDER_MODE=mock ;;
  --live) export WAVECAST_PROVIDER_MODE=live ;;
  *) echo 'Usage: bash scripts/cloud/start-api.sh --mock|--live [--no-tts]' >&2; exit 2 ;;
esac
# Explicit selectors avoid inherited environment settings activating paid work.
export WAVECAST_RECOMMENDATION_PLANNER=deterministic
export WAVECAST_PROPOSAL_PLANNER=inherit WAVECAST_MUSIC_PROVIDER=inherit
export WAVECAST_FAST_START_PROVIDER=inherit WAVECAST_RESEARCH_PROVIDER=inherit
export WAVECAST_CURATOR_PROVIDER=inherit WAVECAST_WRITER_PROVIDER=inherit
export WAVECAST_TTS_PROVIDER=inherit
# --no-tts keeps research/curation/writing live but synthesizes no speech (no MiniMax calls).
[[ "$no_tts" == --no-tts ]] && export WAVECAST_TTS_PROVIDER=mock
export WAVECAST_DATABASE_URL=postgresql+asyncpg://wavecast_cloud:wavecast_cloud@127.0.0.1:5432/wavecast_cloud
export WAVECAST_AUDIO_ROOT="$PWD/.wavecast-data/cloud/audio"
# No production identity or email capabilities are needed by this API.
unset BETTER_AUTH_DATABASE_URL BETTER_AUTH_SECRET WAVECAST_AUTH_JWKS_URL
unset WAVECAST_AUTH_ISSUER WAVECAST_AUTH_AUDIENCE
if [[ "$mode" == --live ]]; then
  python3 - <<'PY'
import os
required = ['DEEPSEEK_API_KEY', 'EXA_API_KEY', 'TAVILY_API_KEY',
            'MINIMAX_API_KEY', 'MINIMAX_TTS_VOICE_ID']
missing = [key for key in required if not os.environ.get(key, '').strip()]
if not any(os.environ.get(key, '').strip() for key in
           ['NETEASE_MUSIC_API_BASE_URL', 'QQ_MUSIC_API_BASE_URL']):
    missing.append('NETEASE_MUSIC_API_BASE_URL or QQ_MUSIC_API_BASE_URL')
if missing:
    raise SystemExit('Missing configuration names: ' + ', '.join(missing))
print('Live configuration present; no provider calls made by this check.')
PY
fi
service postgresql start >/dev/null
if [[ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='wavecast_cloud'")" != 1 ]]; then
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE wavecast_cloud LOGIN PASSWORD 'wavecast_cloud'" >/dev/null
fi
if [[ "$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='wavecast_cloud'")" != 1 ]]; then
  runuser -u postgres -- createdb -O wavecast_cloud wavecast_cloud
fi
mkdir -p "$WAVECAST_AUDIO_ROOT"
uv sync --locked --all-groups
uv run alembic upgrade head
# Foreground: run in a separate background terminal/task when needed.
exec uv run uvicorn services.api.main:app --host 127.0.0.1 --port 8000
