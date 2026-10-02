"""Credential-free checks for CI selection, including actual cumulative Git diffs."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.ci_scope import classify_paths, detect_scope


class PathScopeTests(unittest.TestCase):
    def test_only_web_and_documentation_skip_backend(self) -> None:
        self.assertFalse(
            classify_paths(
                [
                    "apps/web/components/player.tsx",
                    "apps/web/package.json",
                    "apps/web/public/icon.png",
                    "docs/design/example.html",
                    "AGENTS.md",
                ]
            ).backend
        )

    def test_shared_backend_and_unknown_paths_run_full(self) -> None:
        for path in [
            "backend/wavecast/api.py",
            "services/api/main.py",
            "tests/test_api.py",
            "pyproject.toml",
            "uv.lock",
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "vercel.json",
            "Dockerfile.api",
            "docker-compose.prod.yml",
            ".github/workflows/ci.yml",
            "scripts/deployment_smoke.py",
            "packages/shared/schema.ts",
            "new-directory/file.txt",
        ]:
            with self.subTest(path=path):
                self.assertTrue(classify_paths(["apps/web/styles.css", path]).backend)

    def test_main_push_and_manual_run_always_run_full(self) -> None:
        for event_name in ["push", "workflow_dispatch", "unexpected"]:
            self.assertTrue(detect_scope(event_name, {}, Path.cwd()).backend)

    def test_release_pr_runs_full_without_comparison(self) -> None:
        event = {"pull_request": {"base": {"ref": "main"}}}
        self.assertTrue(detect_scope("pull_request", event, Path.cwd()).backend)

    def test_missing_or_malformed_comparison_runs_full(self) -> None:
        for event in [
            {},
            {"pull_request": None},
            {
                "pull_request": {
                    "base": {"ref": "integration", "sha": "--malicious"},
                    "head": {"sha": "0" * 40},
                }
            },
        ]:
            self.assertTrue(detect_scope("pull_request", event, Path.cwd()).backend)


class GitScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "CI test")
        self.git("config", "user.email", "ci-test@example.test")
        self.write("apps/web/original.ts", "original\n")
        self.base = self.commit("base")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    def write(self, path: str, content: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def scope(self, head: str) -> bool:
        event = {
            "pull_request": {
                "base": {"ref": "integration", "sha": self.base},
                "head": {"sha": head},
            }
        }
        return detect_scope("pull_request", event, self.repo).backend

    def test_web_only_diff_skips_backend(self) -> None:
        self.write("apps/web/original.ts", "updated\n")
        self.assertFalse(self.scope(self.commit("web")))

    def test_earlier_backend_commit_is_not_hidden_by_latest_ui_commit(self) -> None:
        self.write("backend/api.py", "backend change\n")
        self.commit("backend")
        self.write("apps/web/original.ts", "web change\n")
        self.assertTrue(self.scope(self.commit("web")))

    def test_rename_from_backend_to_web_still_runs_backend(self) -> None:
        self.write("backend/api.py", "original backend\n")
        self.base = self.commit("backend baseline")
        self.git("mv", "backend/api.py", "apps/web/moved.py")
        self.assertTrue(self.scope(self.commit("rename")))

    def test_backend_deletion_still_runs_backend(self) -> None:
        self.write("backend/api.py", "original backend\n")
        self.base = self.commit("backend baseline")
        (self.repo / "backend/api.py").unlink()
        self.assertTrue(self.scope(self.commit("delete")))

    def test_missing_git_history_runs_full(self) -> None:
        self.assertTrue(self.scope("0" * 40))

    def test_large_diff_is_not_truncated_and_handles_spaced_paths(self) -> None:
        for index in range(310):
            self.write(f"apps/web/assets/file {index}.txt", "asset\n")
        self.write("backend/last.py", "backend change\n")
        self.assertTrue(self.scope(self.commit("large diff")))

    def test_base_branch_changes_do_not_count_as_pr_changes(self) -> None:
        self.write("apps/web/original.ts", "web change\n")
        head = self.commit("web")
        self.git("checkout", "--detach", self.base)
        self.write("backend/unrelated.py", "base-only change\n")
        self.base = self.commit("base advanced")
        self.assertFalse(self.scope(head))


if __name__ == "__main__":
    unittest.main()
