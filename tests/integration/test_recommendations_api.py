from fastapi.testclient import TestClient
from wavecast.proposals import InMemoryProgramProposalRepository
from wavecast.recommendations import InMemoryProgramIdeaRepository
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
    assert other_user.json() == []
