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

### Optional Better Auth identity

WaveCast business migrations remain Alembic-managed. Better Auth owns its
separate PostgreSQL `auth` schema. Configure these server-only values on both
the Vercel Web and Railway API services:

~~~text
WAVECAST_DATABASE_URL=<same private Railway Postgres reference>
BETTER_AUTH_DATABASE_URL=<same private Railway Postgres reference; optional when the WaveCast URL is configured>
BETTER_AUTH_URL=https://<Vercel production domain>
BETTER_AUTH_SECRET=<generated secret>
GOOGLE_CLIENT_ID=<optional>
GOOGLE_CLIENT_SECRET=<optional>
GITHUB_CLIENT_ID=<optional>
GITHUB_CLIENT_SECRET=<optional>
WAVECAST_AUTH_JWKS_URL=https://<Vercel production domain>/api/auth/jwks
WAVECAST_AUTH_ISSUER=https://<Vercel production domain>
WAVECAST_AUTH_AUDIENCE=https://<Vercel production domain>
~~~

OAuth buttons are enabled only for providers with both credentials configured.
Guest browsing, Tune, favorites, library, and listening remain available when
auth is not configured. Before enabling account login against a database, apply
the Better Auth schema separately from Alembic:

~~~sh
pnpm --filter @wavecast/web auth:migrate
~~~

Run that command with `BETTER_AUTH_DATABASE_URL` (preferred) or
`WAVECAST_DATABASE_URL`, plus `BETTER_AUTH_SECRET` and `BETTER_AUTH_URL`,
available to the Web package. When falling back to `WAVECAST_DATABASE_URL`, the
Web app converts the SQLAlchemy-only `postgresql+asyncpg://` scheme to the
standard PostgreSQL URL expected by `pg`. The auth CLI uses the same resolver.
It uses Better Auth's Kysely PostgreSQL adapter and its dedicated `auth`
schema; do not point it at a public or unrelated database.

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
