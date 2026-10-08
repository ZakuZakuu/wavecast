# WaveCast hosted deployment baseline

This credential-free baseline prepares the portable Compose contracts for:

~~~text
GitHub main
├─ Vercel  -> apps/web
└─ Railway -> API + Postgres + Persistent Volume
~~~

## Current release notes (2026-10-06)

The user has completed production domain/login/backend setup and accepted the
live listening flow at https://wavecast.space. The mock instructions below are
the original provisioning baseline, not a claim that today's production is mock.
Do not overwrite production selectors or secrets with those initial defaults.

- Web production follows `main`; human acceptance preview follows `integration`.
  Release using an ordinary merge commit, then fast-forward integration to the
  new main head without rewriting history. Protect and keep both long-lived
  branches. A feature PR alone does not create this project's hosted preview.
- Railway production should track `main`; verify its actual source branch/SHA
  before a release instead of assuming it still tracks integration from earlier
  development. No backend change usually means no backend redeploy is needed.
- GitHub OAuth is configured for the production domain. `BETTER_AUTH_URL` is
  `https://wavecast.space`; callback is
  `https://wavecast.space/api/auth/callback/github`. Railway issuer/audience/JWKS
  must agree with that origin (`/api/auth/jwks` for JWKS). Do not copy secrets into
  docs. Preview login is unavailable by current configuration, not necessarily
  a broken UI; test authenticated flows on the configured production origin.
- The Vercel install command was reported changed to
  `pnpm install --frozen-lockfile --filter @wavecast/web...` so the video workspace
  is not installed for website builds. It is a dashboard setting; confirm before
  relying on it, and do not infer it from the repository alone.
- Vercel ignore-build root-directory handling was fixed in #169 on integration.
  Check the release commit contains that fix; a Git branch SHA is not proof of
  the deployed SHA. If production gets skipped after an equivalent preview,
  Redeploy the intended production commit with **Skip Ignored Build Step**.
  Do not add meaningless main commits to trigger deployment.
- Browser API/audio requests should stay under same-origin `/api/*`, with
  `WAVECAST_INTERNAL_API_URL` supplying server/build routing to Railway. Verify
  manifest/chunk requests as part of real-device acceptance.
- CI and deployment cost rules: [ci.md](ci.md). Batch hosted checkpoints; do not
  use Railway Agent for routine logs or trigger repeated builds for small edits.

## Original provisioning baseline

The remaining sections describe initial safe provisioning and optional provider
activation; current environment values must be checked in the platform.


## Railway API

Connect ZakuZakuu/wavecast on main and select Dockerfile.api. Enable public
networking and use GET /api/health as the health check. Attach one Persistent
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

### Email-code login (Resend)

The Web uses Better Auth's email-OTP plugin; it does not introduce another user
database or require a Railway API change. A verified code signs into the existing
same-email user ID, or creates a verified user for a new email. The account page
shows that email, rather than assuming the first linked OAuth provider was used.
Google remains on basic `openid email profile` scopes; Testing mode has Google's
basic-identity exception and is not restricted to the test-user list for this flow.

Setup order (before releasing/enabling the mail credentials):

1. Create a Resend account and verify a sending subdomain such as
   `auth.wavecast.space`. Add the exact SPF/DKIM/MX records shown in Resend to
   the current DNS provider. Do not replace the website A/CNAME records or an
   existing root-domain mail service. Disable open/click tracking for auth mail.
2. Create a sending-only API key scoped to that verified domain. Configure
   server-only `RESEND_API_KEY` and `WAVECAST_EMAIL_FROM` on the Web; the latter
   can be `WaveCast <login@auth.wavecast.space>`. Do not use `resend.dev` as the
   public sender or put any key in `NEXT_PUBLIC_*`.
3. With the existing auth database/secret/base URL **and both mail variables**
   available, run `pnpm --filter @wavecast/web auth:migrate` against the new code.
   Email OTP uses the existing verification table; database-backed rate limiting
   also requires Better Auth's `rateLimit` table in the same auth schema. This is
   an additive auth-schema migration, not a WaveCast Alembic migration. Inspect
   the proposed migration first; do not reset/delete existing users or accounts.
4. Publish via the normal integration acceptance → main release flow. The email
   form and plugin remain absent until both mail variables exist. Production-only
   auth settings are not implicitly copied to Preview; never enable mail there
   against the production auth database just to test a screenshot.
5. Check `/api/auth/providers` includes `emailOtp: true`. On the configured auth
   origin, test one existing OAuth email (same account/library), one new email,
   expiry/incorrect-code UI and delivery to QQ/163/Gmail inboxes. Unit tests use
   fake mail and an in-memory auth adapter; they do not establish deliverability.

Codes are six digits, expire after five minutes, are stored hashed and have three
incorrect attempts. The UI has a 60-second resend cooldown; the shared database
limiter allows up to three sends per IP per minute (so a shared network is not
limited to a single user). There is no automatic mail-provider retry. Provider
errors are sanitized and the HTTP route reports failed delivery instead of the
library's default misleading success. Do not log OTPs, recipients, provider
bodies, cookies or tokens. Binding/unbinding, changing email and merging accounts
are deferred; different-email OAuth accounts are not implicitly merged.

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

Builds are skipped by `vercel.json` `ignoreCommand`, which runs
`scripts/vercel-ignore-build.sh`: `integration` always builds; other branches
build only when the web app or root workspace files changed since
`VERCEL_GIT_PREVIOUS_SHA`. Vercel runs it from `apps/web`, so the script
compares from the repository root (`tests/ci/test_vercel_ignore_build.py`).
If a production build is ever skipped wrongly, Redeploy it in the dashboard
with "Skip Ignored Build Step".

## First hosted smoke

Keep provider mode mock and verify Web home, same-origin health, opening-only
from-seed, progressive ensure-buffer, audio playback, API redeploy durability,
and Vercel Web reaching Railway through /api/*. Platform binding and public
URLs remain a separate user-operated step.
