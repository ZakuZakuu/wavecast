#!/usr/bin/env bash
# Vercel "Ignored Build Step" for wavecast-web (see vercel.json ignoreCommand).
# Exit 0 skips the build, any other exit builds.
#
# Vercel runs this from the project root directory (apps/web), so every
# path is compared from the repository root: plain pathspecs would be
# resolved relative to apps/web and miss every web change.
set -u

cd "$(git rev-parse --show-toplevel)" || exit 1

# The hosted integration branch always builds (human test checkpoints).
[ "${VERCEL_GIT_COMMIT_REF:-}" = "integration" ] && exit 1

previous="${VERCEL_GIT_PREVIOUS_SHA:-}"
[ -n "$previous" ] || exit 1
git cat-file -e "${previous}^{commit}" 2>/dev/null || exit 1

# Skip only when nothing the web app is built from changed. git diff exits
# 1 on changes and >1 on errors; both build.
git diff --quiet "$previous" HEAD -- \
  apps/web package.json pnpm-lock.yaml pnpm-workspace.yaml vercel.json scripts/vercel-ignore-build.sh
