import json

from fastapi.testclient import TestClient
from wavecast.storage import EpisodeConcurrencyError

import services.api.main as api_module

app = api_module.app


def test_anonymous_listener_header_isolates_episode_access() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/episodes/from-seed/city-pop-misunderstood",
        headers={"X-Wavecast-Listener": "listener-a"},
    ).json()

    denied = client.get(
        f"/api/episodes/{created['id']}", headers={"X-Wavecast-Listener": "listener-b"}
    )

    assert denied.status_code == 404


def test_sse_delivers_the_persisted_episode_snapshot() -> None:
    client = TestClient(app)
    headers = {"X-Wavecast-Listener": "sse-listener"}
    created = client.post("/api/episodes/from-seed/synthpop-return", headers=headers).json()
    client.post(
        f"/api/episodes/{created['id']}/ensure-buffer", headers=headers, json={"target_chapters": 1}
    )

    with client.stream(
        "GET", f"/api/episodes/{created['id']}/events?once=true", headers=headers
    ) as response:
        lines = response.iter_lines()
        event = next(lines)
        assert next(lines) == "event: episode_state_changed"
        data = next(lines)
        next(lines)

    assert event == "id: 2"
    payload = json.loads(data.removeprefix("data: "))
    assert payload["id"] == created["id"]
    assert payload["version"] == 2


def test_concurrent_start_conflict_is_retryable_not_an_internal_error(monkeypatch) -> None:
    def start_conflict(*_args: object, **_kwargs: object) -> None:
        raise EpisodeConcurrencyError("duplicate listener and seed")

    monkeypatch.setattr(api_module.orchestrator, "start_or_resume", start_conflict)

    response = TestClient(app).post("/api/episodes/from-seed/city-pop-misunderstood")

    assert response.status_code == 409
    assert response.json()["detail"] == "Episode creation raced; retry"
