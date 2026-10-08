import pytest
from fastapi.testclient import TestClient
from wavecast.proposals import InMemoryProgramProposalRepository, ProgramProposalGenerationError

from services.api import main as api_module


def test_program_proposal_can_be_created_viewed_and_started() -> None:
    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "proposal-flow-listener"}
    previous_repository = api_module.proposal_repository
    api_module.proposal_repository = InMemoryProgramProposalRepository()

    try:
        response = client.post(
            "/api/program-proposals",
            json={
                "prompt": "下雨的夜晚，想听温柔的爵士，带一点城市感",
                "duration_intent": "SHORT",
                "count": 1,
            },
            headers=headers,
        )

        assert response.status_code == 200
        proposal = response.json()["proposals"][0]
        assert proposal["id"].startswith("proposal-")
        assert proposal["estimated_duration_seconds"] == 22 * 60
        assert proposal["editorial_route"]
        assert proposal["opening_track_ref"] == "mock:opening"

        detail = client.get(f"/api/programs/{proposal['id']}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["id"] == proposal["id"]

        started = client.post(
            f"/api/episodes/from-seed/{proposal['id']}",
            headers=headers,
        )
        assert started.status_code == 200
        episode = started.json()
        assert episode["seed_id"] == proposal["id"]
        assert episode["topic"] == proposal["topic"]
        assert len(episode["segments"]) == 2
        assert episode["segments"][0]["id"] == "segment-opening"
        assert episode["segments"][1]["id"] == "segment-opening-host"
        assert episode["segments"][1]["state"] == "AUDIO_READY"
        assert episode["segments"][1]["narration_role"] == "INTRO"
        assert episode["segments"][0]["kind"] == "MUSIC"
    finally:
        api_module.proposal_repository = previous_repository


def test_invalid_bearer_is_rejected_while_guest_requests_stay_anonymous(monkeypatch) -> None:
    client = TestClient(api_module.app)

    assert client.get("/api/seeds").status_code == 200
    monkeypatch.setattr(api_module, "_auth_verifier", None)
    rejected = client.get("/api/seeds", headers={"Authorization": "Bearer invalid"})
    assert rejected.status_code == 503


def test_valid_bearer_keeps_listener_identity_and_resolves_user(monkeypatch) -> None:
    class FakeVerifier:
        async def verify(self, token: str) -> str:
            assert token == "test-token"
            return "authenticated-user"

    captured: dict[str, str | None] = {}

    class CapturingRepository(InMemoryProgramProposalRepository):
        def save_many(
            self, proposals, *, owner_listener_id=None, owner_user_id=None, source="tune"
        ):
            captured["listener"] = owner_listener_id
            captured["user"] = owner_user_id
            super().save_many(
                proposals,
                owner_listener_id=owner_listener_id,
                owner_user_id=owner_user_id,
                source=source,
            )

    client = TestClient(api_module.app)
    monkeypatch.setattr(api_module, "_auth_verifier", FakeVerifier())
    previous_repository = api_module.proposal_repository
    monkeypatch.setattr(api_module, "proposal_repository", CapturingRepository())
    response = client.post(
        "/api/program-proposals",
        json={"prompt": "测试身份边界", "duration_intent": "AUTO", "count": 1},
        headers={
            "X-Wavecast-Listener": "identity-listener",
            "Authorization": "Bearer test-token",
        },
    )
    assert response.status_code == 200
    assert captured == {"listener": "identity-listener", "user": "authenticated-user"}
    api_module.proposal_repository = previous_repository


def test_static_seed_is_available_through_program_detail_contract() -> None:
    client = TestClient(api_module.app)

    response = client.get("/api/programs/city-pop-misunderstood")

    assert response.status_code == 200
    program = response.json()
    assert program["id"] == "city-pop-misunderstood"
    assert program["editorial_route"]
    assert program["title"] == "你可能一直误解了 City Pop"


def test_proposal_generation_rejects_whitespace_only_prompt() -> None:
    client = TestClient(api_module.app)

    response = client.post(
        "/api/program-proposals",
        json={"prompt": "   ", "duration_intent": "AUTO", "count": 1},
    )

    assert response.status_code == 422


def test_proposal_generation_fails_closed_when_generator_is_unconfigured(monkeypatch) -> None:
    client = TestClient(api_module.app)
    monkeypatch.setattr(api_module, "proposal_generator", None)

    response = client.post(
        "/api/program-proposals",
        json={"prompt": "anything", "duration_intent": "AUTO", "count": 1},
    )

    assert response.status_code == 503


def test_proposal_generation_returns_safe_gateway_error(monkeypatch) -> None:
    class FailingGenerator:
        async def generate(self, body):
            del body
            raise ProgramProposalGenerationError("opening_track_unresolved")

    client = TestClient(api_module.app)
    monkeypatch.setattr(api_module, "proposal_generator", FailingGenerator())

    response = client.post(
        "/api/program-proposals",
        json={"prompt": "unresolvable request", "duration_intent": "AUTO", "count": 1},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Program proposal generation failed (opening_track_unresolved)"
    )


@pytest.mark.parametrize(
    ("reason", "status", "needle"),
    [
        ("opening_track_unplayable", 422, "版权"),
        ("opening_track_not_found", 422, "写法"),
        ("catalog_unavailable", 503, "稍后再试"),
    ],
)
def test_proposal_failures_with_a_known_cause_return_listener_guidance(
    monkeypatch, reason: str, status: int, needle: str
) -> None:
    class FailingGenerator:
        async def generate(self, body):
            del body
            raise ProgramProposalGenerationError(reason)

    client = TestClient(api_module.app)
    monkeypatch.setattr(api_module, "proposal_generator", FailingGenerator())

    response = client.post(
        "/api/program-proposals",
        json={"prompt": "椎名林檎", "duration_intent": "AUTO", "count": 1},
    )

    assert response.status_code == status
    detail = response.json()["detail"]
    assert needle in detail
    assert reason not in detail  # internal codes never reach the listener
    assert "opening_track" not in detail


def test_programme_language_travels_from_request_to_started_episode() -> None:
    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "language-flow-listener"}
    previous_repository = api_module.proposal_repository
    api_module.proposal_repository = InMemoryProgramProposalRepository()

    try:
        response = client.post(
            "/api/program-proposals",
            json={"prompt": "late night synth drive", "count": 1, "output_language": "zh-CN"},
            headers=headers,
        )
        assert response.status_code == 200
        proposal = response.json()["proposals"][0]
        assert proposal["output_language"] == "zh-CN"

        started = client.post(f"/api/episodes/from-seed/{proposal['id']}", headers=headers)
        assert started.status_code == 200
        assert started.json()["output_language"] == "zh-CN"
    finally:
        api_module.proposal_repository = previous_repository
