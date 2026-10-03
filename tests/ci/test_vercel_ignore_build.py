"""Regression tests for the Vercel Ignored Build Step (vercel.json ignoreCommand).

Vercel runs the command from the project's root directory (apps/web). The
original inline command used repository-root pathspecs from there, so every
web change looked like "no change" and the #168 production release was
skipped. These tests run the real ignoreCommand from apps/web in a scratch
repository. Exit 0 = skip the build, anything else = build.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IGNORE_COMMAND = json.loads((REPO / "vercel.json").read_text())["ignoreCommand"]
SCRIPT = REPO / "scripts" / "vercel-ignore-build.sh"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


class VercelIgnoreBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.email", "ci@example.com")
        git(self.root, "config", "user.name", "ci")
        (self.root / "scripts").mkdir()
        shutil.copy(SCRIPT, self.root / "scripts" / SCRIPT.name)
        shutil.copy(REPO / "vercel.json", self.root / "vercel.json")
        (self.root / "apps" / "web").mkdir(parents=True)
        (self.root / "apps" / "web" / "page.tsx").write_text("v1\n")
        (self.root / "services").mkdir()
        (self.root / "services" / "api.py").write_text("v1\n")
        self.previous = self.commit("initial")

    def commit(self, message: str) -> str:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)
        return git(self.root, "rev-parse", "HEAD")

    def ignore(self, ref: str = "main", previous: str | None = None) -> int:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(self.root), "VERCEL_GIT_COMMIT_REF": ref}
        if previous is not None:
            env["VERCEL_GIT_PREVIOUS_SHA"] = previous
        # Exactly as Vercel does: the project root directory is apps/web.
        return subprocess.run(["sh", "-c", IGNORE_COMMAND], cwd=self.root / "apps" / "web", env=env).returncode

    def test_web_change_on_main_builds(self) -> None:
        (self.root / "apps" / "web" / "page.tsx").write_text("v2\n")
        self.commit("web change")
        self.assertNotEqual(self.ignore(previous=self.previous), 0)

    def test_root_dependency_change_builds(self) -> None:
        (self.root / "pnpm-lock.yaml").write_text("lock\n")
        self.commit("lockfile")
        self.assertNotEqual(self.ignore(previous=self.previous), 0)

    def test_backend_only_change_skips(self) -> None:
        (self.root / "services" / "api.py").write_text("v2\n")
        self.commit("backend change")
        self.assertEqual(self.ignore(previous=self.previous), 0)

    def test_release_merge_after_preview_builds(self) -> None:
        # main at the previous release; integration gains web work; main
        # merges it with a merge commit (the #168 shape).
        git(self.root, "checkout", "-q", "-b", "integration")
        (self.root / "apps" / "web" / "page.tsx").write_text("v2\n")
        self.commit("feature")
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "integration", "-m", "release")
        self.assertNotEqual(self.ignore(previous=self.previous), 0)

    def test_integration_always_builds(self) -> None:
        self.assertNotEqual(self.ignore(ref="integration", previous=self.previous), 0)

    def test_missing_or_unknown_previous_sha_builds(self) -> None:
        self.assertNotEqual(self.ignore(previous=None), 0)
        self.assertNotEqual(self.ignore(previous="0" * 40), 0)


if __name__ == "__main__":
    unittest.main()
