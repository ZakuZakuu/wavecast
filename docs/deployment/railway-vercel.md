# WaveCast hosted deployment workflow

This document is the canonical hosted branch/deployment contract for active
WaveCast development. The original deployment baseline assumed direct deployment
from `main`; that is now a **release baseline**, not the routine development
workflow.

## Branch roles

~~~text
feature branch / PR
        |
        v
integration  = hosted human-test / staging checkpoint
  |-- Vercel Preview -> apps/web
  \-- Railway API   -> Dockerfile.api   (during active hackathon testing)

accepted integration checkpoint
        |
        v
main         = public/release branch
  |-- Vercel Production -> apps/web
  \-- Railway API       -> Dockerfile.api   (before public release)
~~~

Rules:

- Do not advance `main` for routine iteration, debugging, or listening tests.
- Merge a feature PR into `integration` only when it forms a coherent hosted
  checkpoint worth human testing; batch small related fixes rather than
  deploying every edit.
- A human listening result is meaningful only when Preview Web and Railway API
  represent the intended matching checkpoint. Generate a **fresh** programme
  after structural generation/arrangement changes; old episodes are immutable
  and do not retroactively acquire fixes.
- Before a public release, promote the accepted `integration` checkpoint to
  `main`, switch/confirm Railway's source branch as `main`, and deploy that
  accepted release SHA.
- Vercel Production branch remains `main`. Vercel deployments from
  `integration` are Preview deployments used for hosted testing.
- During active preliminary testing, Railway may intentionally track
  `integration` so API behavior matches the Vercel Preview.

## Platform incident rule

A platform incident is not an application failure. In particular, if Railway
shows API degradation, slow/stuck deployments, or
`Limited Access — Deploys have been paused temporarily`:

1. keep the last healthy running API in place;
2. stop issuing repeated variable kicks/redeploys that only create duplicate
   queued deployments;
3. do not reconnect the GitHub source or switch `integration`/`main` merely
   to work around the incident;
4. resume with one fresh deployment after Railway restores deploy access;
5. verify deployment SUCCESS, application startup, and `GET /api/health` 200
   before declaring the checkpoint testable.

When diagnosing source state, do not interpret a serialized
`source.commitSha` field alone as proof of a deliberate pin. Confirm the
configured repo/branch in Service Source and use actual deployment metadata
(`commitHash`, branch, status) as the authority for what code is running.

## Release baseline

For a public/release deployment, the topology remains:

~~~text
GitHub main
├─ Vercel  -> apps/web
└─ Railway -> API + Postgres + Persistent Volume
~~~

The sections below describe service configuration. Where they say `main`, read
that as the **release** configuration; active hosted development may temporarily
bind Railway to `integration` according to the branch workflow above.

## Railway API

Connect `ZakuZakuu/wavecast` and select `Dockerfile.api`. Use `integration`
during active hosted testing and `main` for the accepted release. Enable public
networking and use `GET /api/health` as the health check. Attach one Persistent
Volume. Set the first service run UID to 0 because volume ownership may be
root-owned; the image does not silently chmod or chown unknown mounts.

Recommended variables:

~~~text
WAVECAST_DATABASE_URL=<Railway Postgres DATABASE_URL reference>
WAVECAST_PROVIDER_MODE=mock
WAVECAST_RECOMMENDATION_PLANNER=deterministic
RAILWAY_VOLUME_MOUNT_PATH=<attached volume mount path>
~~~

WAVECAST_AUDIO_ROOT wins when explicitly set; otherwise the API uses
RAILWAY_VOLUME_MOUNT_PATH, then .wavecast-data/audio. Railway's PORT is used
by the entrypoint, while local Compose still falls back to 8000. Do not add
railway.toml or railway.json; use Railway dashboard/Git integration.

### Optional AI recommendation inventory

Recommendation inference is gated separately from the global provider mode. Keep
`WAVECAST_PROVIDER_MODE=mock` and set only these values when personalized Home
ideas are ready to use DeepSeek:

~~~text
WAVECAST_RECOMMENDATION_PLANNER=deepseek
DEEPSEEK_API_KEY=<server-only secret>
~~~

This enables one bounded FAST structured DeepSeek call only when a user's
durable recommendation inventory needs generation or refill. Ordinary Home
reads reuse Postgres inventory and do not call the model. Provider failures fall
back to the deterministic planner for that refresh. Switching planner source
invalidates the old source's visible inventory immediately, so previously
cached heuristic cards do not occupy the 24-hour cooldown. This setting does
not enable live episode assembly, MiniMax TTS, search providers, or music
providers.

### Staged live-provider activation

Keep `WAVECAST_PROVIDER_MODE=mock` as the hosted safety default. The remaining
provider graph can be activated without another code deploy by setting only the
capabilities being validated:

~~~text
WAVECAST_PROPOSAL_PLANNER=inherit   # mock | deepseek
WAVECAST_MUSIC_PROVIDER=inherit     # mock | auto | netease | qqmusic | audius
WAVECAST_FAST_START_PROVIDER=inherit # mock | deepseek
WAVECAST_RESEARCH_PROVIDER=inherit  # mock | live (DeepSeek planner + Exa/Tavily)
WAVECAST_CURATOR_PROVIDER=inherit   # mock | deepseek
WAVECAST_WRITER_PROVIDER=inherit    # mock | deepseek
WAVECAST_TTS_PROVIDER=inherit       # mock | minimax
~~~

`inherit` follows the global mode, so the current production environment keeps
all of these mock until an explicit selector is changed. A live selector is
fail-closed: missing credentials or a missing music endpoint should block that
deployment instead of silently calling a mock provider.

Recommended rollout order after the wiring deploy:

~~~text
1. proposal=deepseek + music=<real provider>
2. fast_start=deepseek + research=live + curator=deepseek
3. writer=deepseek
4. tts=minimax
~~~

For the first MiniMax production run, configure `MINIMAX_API_KEY` and
`MINIMAX_TTS_VOICE_ID`. The code defaults are
`MINIMAX_TTS_MODEL=speech-2.8-turbo` and `MINIMAX_TTS_SPEED=0.8`; set
environment overrides only when testing another model or pace.

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
