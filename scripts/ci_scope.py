"""Select expensive CI jobs conservatively, without API pagination or extra actions."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Scope:
    backend: bool
    reason: str


def classify_paths(paths: Iterable[str]) -> Scope:
    # Only these paths are known not to change backend/deployment behaviour.
    # Everything else (including newly introduced directories) runs full CI.
    for path in paths:
        if path.startswith(("apps/web/", "docs/")):
            continue
        if path in {"README.md", "AGENTS.md", "LICENSE"}:
            continue
        return Scope(True, "backend, shared configuration, or unrecognised path changed")
    return Scope(False, "only web/documentation paths changed")


def detect_scope(event_name: str, event: dict[str, Any], repo: Path) -> Scope:
    # Main releases and manual runs always validate the entire stack.
    if event_name != "pull_request":
        return Scope(True, "release/manual/non-PR run")
    try:
        pr = event["pull_request"]
        if pr["base"]["ref"] == "main":
            return Scope(True, "release PR targeting main")
        base, head = pr["base"]["sha"], pr["head"]["sha"]
        if not all(
            isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha) for sha in (base, head)
        ):
            raise ValueError("invalid comparison commits")
        # Triple-dot compares the PR's complete cumulative diff, not its last
        # commit. Disable rename detection so both old and new paths are checked.
        changed = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}", "--"],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
        return classify_paths(os.fsdecode(path) for path in changed.split(b"\0") if path)
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return Scope(True, "comparison unavailable; running full CI")


def main() -> None:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        scope = detect_scope(os.environ.get("GITHUB_EVENT_NAME", ""), event, Path.cwd())
    except (KeyError, ValueError, OSError):
        scope = Scope(True, "event unavailable; running full CI")
    result = f"backend={str(scope.backend).lower()}\n"
    print(result.strip() + ": " + scope.reason)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a") as stream:
            stream.write(result)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as stream:
            stream.write(
                f"Backend and deployment smoke: **{'run' if scope.backend else 'skip'}**. "
                f"{scope.reason}. Web checks always run.\n"
            )


if __name__ == "__main__":
    main()
