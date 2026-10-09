import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from wavecast.proposals import (
    DeterministicMockProgramProposalGenerator,
    InMemoryProgramProposalRepository,
)
from wavecast.recommendations import InMemoryProgramIdeaRepository
from wavecast.storage import (
    InMemoryGenerationQuotaRepository,
    InMemoryUserLibraryRepository,
)
from wavecast.storage.recommendations import PostgresProgramIdeaRepository
from wavecast.user_context import (
    Genre,
    InMemoryUserEventRepository,
    InMemoryUserPreferencesRepository,
    Mood,
    UserEventInput,
    UserEventService,
    UserEventType,
    UserPreferences,
)

from services.api import main as api_module


def test_recommendation_refresh_is_authenticated_personalized_and_rate_limited(monkeypatch) -> None:
    class FakeVerifier:
        async def verify(self, token: str) -> str:
            return {"token-a": "user-a", "token-b": "user-b"}[token]

    preferences = InMemoryUserPreferencesRepository()
    preferences.save(
        UserPreferences(
            user_id="user-a",
            genres=[Genre.R_AND_B],
            moods=[Mood.FOCUS],
            onboarding_completed=True,
        )
    )
    events = InMemoryUserEventRepository()
    event_service = UserEventService(events)
    event_service.record(
        user_id="user-a",
        event=UserEventInput(
            event_type=UserEventType.PLAY_COMPLETE,
            program_id="city-pop-misunderstood",
        ),
    )
    monkeypatch.setattr(api_module, "_auth_verifier", FakeVerifier())
    monkeypatch.setattr(api_module, "user_preferences_repository", preferences)
    monkeypatch.setattr(api_module, "_user_event_repository", events)
    monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
    monkeypatch.setattr(api_module, "recommendation_repository", InMemoryProgramIdeaRepository())
    client = TestClient(api_module.app)

    assert client.get("/api/recommendations/me").status_code == 401
    headers_a = {"Authorization": "Bearer token-a"}
    first = client.post("/api/recommendations/me/refresh", headers=headers_a)

    assert first.status_code == 200
    payload = first.json()
    assert len(payload) >= 2
    assert any("R&B" in idea["title"] and "Focus" in idea["title"] for idea in payload)
    assert any("City Pop" in " ".join(idea["tags"]) for idea in payload)
    assert all("user_id" not in idea for idea in payload)

    second = client.post("/api/recommendations/me/refresh", headers=headers_a)
    listed = client.get("/api/recommendations/me", headers=headers_a)
    other_user = client.get(
        "/api/recommendations/me",
        headers={"Authorization": "Bearer token-b"},
    )

    assert [idea["id"] for idea in second.json()] == [idea["id"] for idea in payload]
    assert [idea["id"] for idea in listed.json()] == [idea["id"] for idea in payload]
    assert other_user.status_code == 200
    assert other_user.json()
    assert all("R&B" not in idea["title"] for idea in other_user.json())


def test_a_provider_failure_while_materialising_an_idea_is_logged(monkeypatch, caplog) -> None:
    from wavecast.providers.errors import ProviderInvalidResponseError

    class FakeVerifier:
        async def verify(self, token: str) -> str:
            return "user-a"

    class FailingGenerator:
        async def generate(self, body):
            del body
            raise ProviderInvalidResponseError("deepseek request failed with HTTP 402")

    monkeypatch.setattr(api_module, "_auth_verifier", FakeVerifier())
    monkeypatch.setattr(
        api_module, "user_preferences_repository", InMemoryUserPreferencesRepository()
    )
    monkeypatch.setattr(api_module, "_user_event_repository", InMemoryUserEventRepository())
    monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
    monkeypatch.setattr(api_module, "recommendation_repository", InMemoryProgramIdeaRepository())
    monkeypatch.setattr(api_module, "proposal_generator", FailingGenerator())
    monkeypatch.setattr(
        api_module, "generation_quota_repository", InMemoryGenerationQuotaRepository()
    )
    monkeypatch.setattr(api_module, "user_library_repository", InMemoryUserLibraryRepository())
    client = TestClient(api_module.app)
    headers = {"Authorization": "Bearer token-a"}
    idea_id = client.get("/api/recommendations/me", headers=headers).json()[0]["id"]

    with caplog.at_level("WARNING", logger=api_module.logger.name):
        response = client.post(
            f"/api/recommendations/me/{idea_id}/program-proposal", headers=headers
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Program proposal provider failed"
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "program_proposal_provider_failed" in logged and "HTTP 402" in logged


def test_recommendation_materialization_is_owned_quota_bound_and_single_use(monkeypatch) -> None:
    class FakeVerifier:
        async def verify(self, token: str) -> str:
            return {"token-a": "user-a", "token-b": "user-b"}[token]

    ideas = InMemoryProgramIdeaRepository()
    proposals = InMemoryProgramProposalRepository()
    monkeypatch.setattr(api_module, "_auth_verifier", FakeVerifier())
    monkeypatch.setattr(
        api_module,
        "user_preferences_repository",
        InMemoryUserPreferencesRepository(),
    )
    monkeypatch.setattr(api_module, "_user_event_repository", InMemoryUserEventRepository())
    monkeypatch.setattr(api_module, "proposal_repository", proposals)
    monkeypatch.setattr(api_module, "recommendation_repository", ideas)
    monkeypatch.setattr(
        api_module,
        "proposal_generator",
        DeterministicMockProgramProposalGenerator(),
    )
    monkeypatch.setattr(
        api_module,
        "generation_quota_repository",
        InMemoryGenerationQuotaRepository(),
    )
    monkeypatch.setattr(
        api_module,
        "user_library_repository",
        InMemoryUserLibraryRepository(),
    )
    client = TestClient(api_module.app)
    headers_a = {"Authorization": "Bearer token-a"}
    headers_b = {"Authorization": "Bearer token-b"}

    inventory = client.get("/api/recommendations/me", headers=headers_a)
    assert inventory.status_code == 200
    idea = inventory.json()[0]
    idea_id = idea["id"]

    other_user = client.post(
        f"/api/recommendations/me/{idea_id}/program-proposal",
        headers=headers_b,
    )
    assert other_user.status_code == 404

    generated = client.post(
        f"/api/recommendations/me/{idea_id}/program-proposal",
        headers=headers_a,
    )
    assert generated.status_code == 200
    proposal = generated.json()["proposals"][0]
    proposal_id = proposal["id"]
    assert proposal["title"] == idea["title"]
    assert proposal["short_description"] == idea["description"]
    assert proposal["genre_tags"] == idea["tags"][:8]
    assert proposal["mood_tags"] == []
    assert proposal["opening_track_ref"] == "mock:opening"
    assert proposal["anchor_artists"] == []
    assert proposals.get_for_user("user-a", proposal_id) is not None
    assert proposals.get_for_user("user-b", proposal_id) is None

    repeated = client.post(
        f"/api/recommendations/me/{idea_id}/program-proposal",
        headers=headers_a,
    )
    assert repeated.status_code == 409

    refreshed_inventory = client.get("/api/recommendations/me", headers=headers_a)
    assert refreshed_inventory.status_code == 200
    assert idea_id not in {idea["id"] for idea in refreshed_inventory.json()}
    assert len(refreshed_inventory.json()) >= 2


def test_postgres_recommendation_materialization_does_not_nest_event_loop(monkeypatch) -> None:
    database_url = os.getenv("WAVECAST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set WAVECAST_TEST_DATABASE_URL to run Postgres integration tests")

    user_id = f"recommendation-api-{uuid4().hex}"
    token = f"token-{uuid4().hex}"

    class FakeVerifier:
        async def verify(self, candidate: str) -> str:
            assert candidate == token
            return user_id

    ideas = PostgresProgramIdeaRepository(database_url)
    proposals = InMemoryProgramProposalRepository()
    monkeypatch.setattr(api_module, "_auth_verifier", FakeVerifier())
    monkeypatch.setattr(
        api_module,
        "user_preferences_repository",
        InMemoryUserPreferencesRepository(),
    )
    monkeypatch.setattr(api_module, "_user_event_repository", InMemoryUserEventRepository())
    monkeypatch.setattr(api_module, "proposal_repository", proposals)
    monkeypatch.setattr(api_module, "recommendation_repository", ideas)
    monkeypatch.setattr(
        api_module,
        "proposal_generator",
        DeterministicMockProgramProposalGenerator(),
    )
    monkeypatch.setattr(
        api_module,
        "generation_quota_repository",
        InMemoryGenerationQuotaRepository(),
    )
    monkeypatch.setattr(
        api_module,
        "user_library_repository",
        InMemoryUserLibraryRepository(),
    )
    client = TestClient(api_module.app)
    headers = {"Authorization": f"Bearer {token}"}

    try:
        inventory = client.get("/api/recommendations/me", headers=headers)
        assert inventory.status_code == 200
        idea_id = inventory.json()[0]["id"]

        generated = client.post(
            f"/api/recommendations/me/{idea_id}/program-proposal",
            headers=headers,
        )

        assert generated.status_code == 200
        proposal_id = generated.json()["proposals"][0]["id"]
        assert proposals.get_for_user(user_id, proposal_id) is not None
    finally:
        ideas.close()
