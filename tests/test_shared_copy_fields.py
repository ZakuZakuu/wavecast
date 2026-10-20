"""What `shared_copy` still guarantees. Links no longer use it (they play the published programme),
so this stays only as long as the function does."""

import pytest
from wavecast.proposals import InMemoryProgramProposalRepository

from services.api import main as api_module

OWNER = {"X-Wavecast-Listener": "share-owner-listener"}


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
    from fastapi.testclient import TestClient

    client = TestClient(api_module.app)
    created = client.post(
        "/api/program-proposals",
        json={"prompt": "下雨的夜晚，想听温柔的爵士", "duration_intent": "SHORT", "count": 1},
        headers=OWNER,
    )
    assert created.status_code == 200
    return client, created.json()["proposals"][0]


# Every field of a programme is either copied as it is or made again for the visitor. A new field
# added to ProgramProposal fails the test below until someone decides which it is.
COPIED_AS_IS = {
    "title", "short_description", "cover_title", "estimated_duration_seconds", "opening_track_ref",
    "opening_track_title", "opening_track_spoken_title", "opening_track_cover_url", "opening_track_artist", "opening_track_duration_seconds",
    "opening_track_timing_profile", "cover", "editorial_route", "genre_tags", "mood_tags",
    "anchor_artists", "presentation_intent", "output_language", "station", "required_artists",
    "generation_profile", "opening_host_note",
}
# Internal research stays with the owner's proposal; a legacy copy starts without it.
MADE_AGAIN = {"id", "topic", "opening_narration_text", "created_at", "opening_evidence"}


def test_every_field_of_a_shared_copy_is_decided() -> None:
    assert set(api_module.ProgramProposal.model_fields) == COPIED_AS_IS | MADE_AGAIN


def test_the_copy_is_opened_without_the_sharers_request(shared) -> None:
    from wavecast.proposals import shared_copy

    _, proposal = shared
    secret = "给我女朋友的生日准备一档她会喜欢的"
    original = api_module.ProgramProposal(
        **{
            **proposal,
            "topic": secret,
            "opening_narration_text": f"现在先来听《Neon First Light》，来自你点的Mira Fields。{secret}",
        }
    )

    copy = shared_copy(original, new_id="proposal-" + "cd34" * 8)

    assert copy.opening_narration_text
    assert "你点" not in copy.opening_narration_text and secret not in copy.opening_narration_text
    assert copy.opening_track_ref == original.opening_track_ref
    for name in COPIED_AS_IS:
        assert getattr(copy, name) == getattr(original, name), name
