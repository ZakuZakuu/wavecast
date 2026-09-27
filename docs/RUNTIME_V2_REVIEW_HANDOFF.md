# Runtime v2 adaptive buffer review handoff

Base: `53bdde72ab64d043d5b27d2f07055447959d494c`.
Branch: `codex/runtime-v2-adaptive-buffer`.

User requested an early wrap-up due to the five-hour usage window. No merge,
deployment, live/paid calls, or browser review transport was performed.

## Implemented

- Shared deterministic API/orchestrator buffer decision: ready successor,
  playable duration, browser current-source remaining, bounded per-Episode
  successful refill latency, PROGRESSIVE/FULL, and chapter cap.
- Healthy buffers skip expensive planning while preserving ended-source recovery.
- Latency is stored in existing Episode JSON (old snapshots compatible).
- Updated ADR0020 and PROJECT_STATE; small pre-existing lint/type cleanup.

## Validation

- Ruff clean; mypy passed all 88 source files.
- Web lint/typecheck, 63 tests, production build passed.
- Isolated Postgres runtime/job tests: 6 passed, including latency roundtrip.
- Most recent full backend run: 518 passed, 25 skipped, 1 failed. The failure
  was the old eager-planning expectation in
  `test_existing_ready_successor_skips_duplicate_fast_bootstrap`.
  The test now asserts healthy deferral followed by planning for an unmet target;
  focused validation is run after that update. Full suite must be rerun on final HEAD.
- Postgres tests used a dedicated loopback container, not existing application DBs.

## Reviewer / next implementer

1. Review adaptive threshold and healthy-plan deferral against ADR0020.
2. Rerun backend full suite on final HEAD before approval/merge; required CI is
   a merge gate, not the development feedback loop.
3. Urgency is an explicit decision flag, not new queue priority/preemption.
4. Latency is successful refill wall time, not global provider percentiles;
   failed/deferred refills do not contribute samples.
5. Worker lease/listener hardening and arrangement/DJ milestones are NOT done.

Isolated checkout: `C:\Users\Lenovo\.codex\worktrees\runtime-v2-buffer\wavecast`.
WSL Python environment: `/tmp/wavecast-runtime-v2-venv`.
For WSL git use explicit metadata because the app created a Windows-style pointer:
`git --git-dir=/home/lenovo/Playground/wavecast/.git/worktrees/wavecast4 --work-tree=/mnt/c/Users/Lenovo/.codex/worktrees/runtime-v2-buffer/wavecast -c core.autocrlf=true ...`
Original user checkout was not switched or edited.
