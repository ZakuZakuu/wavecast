# WaveCast Development Workflows

WaveCast supports two primary execution modes and one recommended hybrid mode.
They share the same product contracts, branch discipline, and review standards;
the difference is **where code execution happens**.

## 1. Browser ChatGPT orchestration mode

Use this mode when ChatGPT is operating through connected cloud services such
as GitHub, Vercel, and Railway.

Best for:

- product/architecture planning and milestone control;
- reading/reviewing PRs and repository state;
- small remote code or documentation edits;
- checking CI, hosted logs, deployments, variables, and health;
- coordinating a hosted human-test checkpoint;
- reviewing work produced by another agent.

Constraints:

- Browser ChatGPT does not implicitly control the user's local Windows/WSL
  filesystem or local dev processes.
- Cloud connector success is not a substitute for local execution when the task
  requires local build/debug feedback.
- Platform outages such as Railway deployment pauses may block hosted
  verification but should not block ordinary development.

Typical loop:

~~~text
read product/state docs
 -> inspect GitHub state
 -> plan a coherent change
 -> edit/review on a feature branch
 -> observe CI
 -> merge coherent checkpoint to integration
 -> deploy only when a hosted human test is useful
 -> review listener feedback
~~~

Do not advance `main` for routine work. During preliminary development,
`integration` remains the hosted staging/test branch.

## 2. Local agent execution mode

Use this mode when Codex or another coding agent is running against the user's
local WaveCast checkout, normally under Windows/WSL.

Best for:

- implementation-heavy work;
- running the backend/frontend locally;
- fast edit-test-debug loops;
- ffmpeg/audio debugging;
- unit/integration tests and production builds;
- repository-wide refactors;
- work that should continue while hosted infrastructure is unavailable.

The local agent should own execution:

- edit files in the local checkout;
- run the exact relevant lint/type/test/build commands;
- inspect local logs and generated artifacts;
- keep commits small and reviewable;
- work on a feature branch rather than directly on `integration` or `main`.

Typical loop:

~~~text
git fetch
 -> branch from latest integration
 -> implement locally
 -> run targeted tests
 -> run required merge-level checks
 -> commit
 -> push feature branch
 -> open/update PR
 -> review
 -> merge to integration only at a coherent hosted checkpoint
~~~

A Railway/Vercel incident does **not** require stopping this loop. Continue
locally and defer only the hosted acceptance test.

## 3. C2C hybrid mode — preferred for substantial work

When the Codex-with-ChatGPT bridge is available, use a split-responsibility
workflow:

- **Local Codex/agent = execution layer**
  - edits code;
  - runs commands/tests/builds;
  - reproduces bugs locally;
  - pushes commits/PR updates.
- **Browser ChatGPT = planning/review layer**
  - keeps product scope aligned with the preliminary target;
  - reviews implementation and PR diffs;
  - decides whether a checkpoint is worth hosting;
  - inspects GitHub/Vercel/Railway when cloud validation is needed.

This avoids forcing Browser ChatGPT to emulate a local shell and avoids forcing
the local agent to own long-horizon product decisions.

The C2C bridge is a communication/review channel, not a second source of truth.
Git, tests, and repository docs remain authoritative.

## 4. Ownership and conflict rules

Do not let Browser ChatGPT and a local agent independently edit the same branch
or files at the same time.

Choose one execution owner for each task:

- if the local agent owns implementation, Browser ChatGPT should review rather
  than make overlapping remote commits;
- if Browser ChatGPT has already made remote commits, the local agent must
  fetch/rebase or reset to the agreed branch head before continuing;
- do not copy-paste parallel fixes into two branches and reconcile later unless
  explicitly planned.

At every handoff, communicate:

- repository + branch;
- exact head SHA;
- PR number if one exists;
- tests already run and their results;
- known runtime/deployment blockers;
- the next concrete acceptance condition.

## 5. Which mode should be used now?

During a hosted deployment outage, prefer **Local Agent execution mode** for new
implementation work.

For the current preliminary milestone:

- keep #146 as the pending hosted Listening P0 checkpoint until Railway can
  deploy it;
- continue independent UI P0 or other locally verifiable work on feature
  branches if desired;
- do not merge speculative runtime changes into the unverified #146 listening
  checkpoint merely because hosted testing is unavailable;
- use Browser ChatGPT for scope control, review, documentation, and eventual
  hosted verification after Railway recovers.

## 6. Shared merge/deployment discipline

Regardless of execution mode:

- `main` = public/release branch;
- `integration` = hosted human-test/staging branch;
- feature branches = normal implementation work;
- CI/local checks must be observed before merge;
- hosted deployment is an explicit acceptance checkpoint, not part of every
  coding iteration;
- generate a fresh programme for human listening after structural runtime or
  arrangement changes.
