# WaveCast hosted deployment baseline

This credential-free baseline prepares the portable Compose contracts for:

~~~text
GitHub main
├─ Vercel  -> apps/web
└─ Railway -> API + Postgres + Persistent Volume
~~~

Initial hosted provider mode remains mock. Do not create platform resources,
store credentials, enable live providers, or add music sidecars in this step.

## Railway API

Connect ZakuZakuu/wavecast on main and select Dockerfile.api. Enable public
networking and use GET /api/health as the health check. Attach one Persistent
Volume. Set the first service run UID to 0 because volume ownership may be
root-owned; the image does not silently chmod or chown unknown mounts.

Recommended variables:

~~~text
WAVECAST_DATABASE_URL=<Railway Postgres DATABASE_URL reference>
WAVECAST_PROVIDER_MODE=mock
RAILWAY_VOLUME_MOUNT_PATH=<attached volume mount path>
~~~

WAVECAST_AUDIO_ROOT wins when explicitly set; otherwise the API uses
RAILWAY_VOLUME_MOUNT_PATH, then .wavecast-data/audio. Railway's PORT is used
by the entrypoint, while local Compose still falls back to 8000. Do not add
railway.toml or railway.json; use Railway dashboard/Git integration.

## Vercel Web

Import the same repository as a separate Vercel project:

~~~text
Root Directory: apps/web
Production branch: main
WAVECAST_INTERNAL_API_URL=https://<Railway API public domain>
~~~

The browser continues to call same-origin /api/*; the Next build rewrites that
route to the Railway service. The variable is server/build routing config, not
a browser credential.

## First hosted smoke

Keep provider mode mock and verify Web home, same-origin health, opening-only
from-seed, progressive ensure-buffer, audio playback, API redeploy durability,
and Vercel Web reaching Railway through /api/*. Platform binding and public
URLs remain a separate user-operated step.
