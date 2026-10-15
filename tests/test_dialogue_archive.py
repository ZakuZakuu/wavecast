"""The archived 2026-10-15 portrait run is kept exactly as it was, as history.

It records an experiment made while a post-hoc model check and repair still existed (ADR 0028);
that path has since been retired (ADR 0029), so nothing here exercises any code.  These tests
only guard the archive: untouched, and free of credentials.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "dialogue_portrait_20261015"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_the_archive_is_intact_and_holds_no_credentials() -> None:
    manifest = load("MANIFEST.json")
    assert manifest["acceptance_status"] == "人物志单段经过一次局部修复后通过，用户试听认可"
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest, name
    assert manifest["information_loss"]["recorded_not_redone"] is True
    assert manifest["audio_attachment"]["kept_outside_the_repository"] is True
    for path in FIXTURES.iterdir():
        text = path.read_text(encoding="utf-8").lower()
        assert not any(marker in text for marker in ("api_key", "bearer ", "x-api-key", "access_token")), path.name


def test_the_archived_material_and_candidate_still_load_with_todays_models() -> None:
    from wavecast.models.dialogue import DialogueDraft
    from wavecast.models.story_material import StoryMaterial

    material = StoryMaterial.model_validate(load("material.normalized.json")["material"])
    draft = DialogueDraft.model_validate(
        {"turns": [{k: v for k, v in turn.items()} for turn in load("candidate.unchecked.json")["turns"]]}
    )
    assert {ref for turn in draft.turns for ref in turn.fact_refs} <= set(material.fact_ids)
