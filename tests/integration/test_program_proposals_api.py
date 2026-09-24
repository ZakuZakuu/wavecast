from fastapi.testclient import TestClient
from wavecast.proposals import ProgramProposalGenerationError

from services.api import main as api_module


def test_program_proposal_can_be_created_viewed_and_started() -> None:
    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "proposal-flow-listener"}

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
    assert len(episode["segments"]) == 1
    assert episode["segments"][0]["kind"] == "MUSIC"


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
