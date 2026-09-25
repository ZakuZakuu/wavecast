from __future__ import annotations

from fastapi.testclient import TestClient
from wavecast.auth import AuthTokenError
from wavecast.user_context import (
    InMemoryUserEventRepository,
    InMemoryUserPreferencesRepository,
    UserEventService,
)

from services.api import main as api_module


class FakeVerifier:
    async def verify(self, token: str) -> str:
        if token == "invalid":
            raise AuthTokenError("invalid_token")
        return token.removeprefix("user:")


def _client(monkeypatch):
    monkeypatch.setattr(api_module, "_auth_verifier", FakeVerifier())
    monkeypatch.setattr(
        api_module, "user_preferences_repository", InMemoryUserPreferencesRepository()
    )
    event_repository = InMemoryUserEventRepository()
    monkeypatch.setattr(api_module, "user_event_service", UserEventService(event_repository))
    return TestClient(api_module.app), event_repository


def test_preferences_are_authenticated_owned_and_crud(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    assert client.get("/api/user-preferences/me").status_code == 401
    assert (
        client.get(
            "/api/user-preferences/me", headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )

    user_a = {"Authorization": "Bearer user:alice"}
    user_b = {"Authorization": "Bearer user:bob"}
    initial = client.get("/api/user-preferences/me", headers=user_a)
    assert initial.status_code == 200
    assert initial.json()["user_id"] == "alice"
    assert initial.json()["onboarding_completed"] is False

    updated = client.put(
        "/api/user-preferences/me",
        headers=user_a,
        json={
            "genres": ["City Pop", "R&B"],
            "artists": ["方大同"],
            "moods": ["Late Night", "Discovery"],
            "contexts": ["夜间散步"],
            "discovery_level": "ADVENTUROUS",
            "onboarding_completed": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["user_id"] == "alice"
    assert updated.json()["genres"] == ["City Pop", "R&B"]
    assert client.get("/api/user-preferences/me", headers=user_a).json() == updated.json()

    other_user = client.get("/api/user-preferences/me", headers=user_b)
    assert other_user.status_code == 200
    assert other_user.json()["user_id"] == "bob"
    assert other_user.json()["genres"] == []

    deleted = client.delete("/api/user-preferences/me", headers=user_a)
    assert deleted.status_code == 200
    assert deleted.json()["genres"] == []
    assert deleted.json()["onboarding_completed"] is False


def test_event_creation_uses_verified_owner_and_rejects_guests(monkeypatch) -> None:
    client, repository = _client(monkeypatch)
    assert client.post("/api/user-events", json={"event_type": "LIKE"}).status_code == 401

    response = client.post(
        "/api/user-events",
        headers={"Authorization": "Bearer user:alice"},
        json={"event_type": "PLAY_START", "program_id": "program-1"},
    )
    assert response.status_code == 201
    assert response.json()["event_type"] == "PLAY_START"
    assert response.json()["program_id"] == "program-1"
    assert repository.list_for_user("alice")[0].user_id == "alice"
    assert repository.list_for_user("user:mallory") == []

    invalid = client.post(
        "/api/user-events",
        headers={"Authorization": "Bearer user:alice"},
        json={"event_type": "LIKE", "user_id": "mallory", "raw_prompt": "no"},
    )
    assert invalid.status_code == 422
