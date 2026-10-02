# CI during development

Develop normally on a feature branch and open a PR. GitHub Actions selects the
checks automatically; no local setup, new secrets, or Claude configuration is
needed. The hosted `integration` preview/deployment procedure is unchanged.

| Change/event | Web checks | Backend + deployment smoke |
| --- | --- | --- |
| PR containing only `apps/web/**`, `docs/**`, README.md, AGENTS.md, LICENSE | Full | Skipped |
| PR changing backend, tests, scripts, root dependencies, deployment/CI configuration, or any other path | Full | Full |
| PR targeting `main`, push to `main`, or manual CI run | Full | Full |
| Missing comparison data/history or failed scope selection | Full | Full |

Web checks retain lint, typecheck, frontend tests, production build, and the
same-origin API rewrite smoke. Backend checks retain PostgreSQL migrations,
lint, mypy, and the complete pytest suite. Deployment smoke retains the Docker
build, startup, API restart and persistence checks. No paid provider calls are
introduced. These checks do not replace real-device listening acceptance.

The `changes` job uses the complete cumulative PR Git diff against its merge
base, including deleted files and both sides of renames. It does not query the
paginated PR files API or look only at the last commit. Only known web/docs
paths can skip expensive checks; unfamiliar paths default to full validation.

The workflow still runs for every PR, and `web`, `backend`, and
`deployment-smoke` keep their existing check names. Only individual jobs are
conditionally skipped, avoiding missing/pending workflow checks. If scope
tests fail, the workflow fails and the expensive jobs still run conservatively.

For a full-stack checkpoint on any branch, select **Actions → CI → Run
workflow** once the updated workflow is also on the default branch (`main`).
Until then, a PR targeting `main` still runs everything before release; do not
advance `main` just to expose the manual-run button.

Scope tests can also run locally without installing application dependencies:

```sh
python3 -m unittest discover -s tests/ci -p 'test_*.py' -v
```
