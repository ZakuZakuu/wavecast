from fastapi.testclient import TestClient

from services.api.main import app


def _materialized_payload(audio_url: str) -> dict[str, object]:
    return {
        "seed_id": "external-url-boundary",
        "title": "External URL boundary",
        "topic": "Runtime safety",
        "estimated_duration_seconds": 12,
        "playable_episode": {
            "id": "external-url-episode",
            "segments": [
                {
                    "id": "external-url-track",
                    "chapter_id": "chapter-1",
                    "order": 0,
                    "kind": "MUSIC",
                    "state": "AUDIO_READY",
                    "planned_duration_seconds": 12,
                    "actual_duration_seconds": 12,
                    "track_ref": "audius:track-1",
                    "audio_source_url": audio_url,
                    "title": "Track",
                    "artist": "Artist",
                }
            ],
        },
    }


def test_materialized_import_rejects_external_audio_url() -> None:
    response = TestClient(app).post(
        "/api/episodes/from-materialized",
        json=_materialized_payload("https://cdn.example.test/temporary.mp3"),
        headers={"X-Wavecast-Listener": "external-url-listener"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "materialized episode contains an external audio URL"


def test_mock_vertical_slice_from_seed_to_materialized_resumeable_episode() -> None:
    client = TestClient(app)
    seeds = client.get("/api/seeds").json()
    assert seeds

    created = client.post(f"/api/episodes/from-seed/{seeds[0]['id']}")
    assert created.status_code == 200
    episode = created.json()
    episode_id = episode["id"]
    assert episode["generated_frontier_seconds"] == 22
    assert episode["buffer_ahead_seconds"] == 22

    seeked = client.post(f"/api/episodes/{episode_id}/seek", json={"position_seconds": 10})
    assert seeked.status_code == 200
    assert seeked.json()["buffer_ahead_seconds"] == 12

    assert (
        client.post(f"/api/episodes/{episode_id}/seek", json={"position_seconds": 10}).status_code
        == 200
    )
    too_far = client.post(f"/api/episodes/{episode_id}/seek", json={"position_seconds": 23})
    assert too_far.status_code == 409

    buffered = client.post(
        f"/api/episodes/{episode_id}/ensure-buffer", json={"target_chapters": 1}
    )
    assert buffered.status_code == 200

    next_response = client.post(f"/api/episodes/{episode_id}/next")
    assert next_response.status_code == 200
    assert next_response.json()["current_segment_id"].startswith("chapter-2:")
    assert "progressive_session" not in buffered.json()

    assert client.post(f"/api/episodes/{episode_id}/leave").json()["is_listener_active"] is False
    assert client.post(f"/api/episodes/{episode_id}/advance").status_code == 409
    assert client.post(f"/api/episodes/{episode_id}/resume").json()["is_listener_active"] is True

    materialized = client.post(f"/api/episodes/{episode_id}/materialize")
    result = materialized.json()
    assert result["state"] == "MATERIALIZED"
    assert result["generated_frontier_seconds"] == result["estimated_total_seconds"]


def test_reentering_a_seed_resumes_the_same_episode_session() -> None:
    client = TestClient(app)
    seed_id = client.get("/api/seeds").json()[1]["id"]
    first = client.post(f"/api/episodes/from-seed/{seed_id}").json()
    client.post(f"/api/episodes/{first['id']}/leave")

    reentered = client.post(f"/api/episodes/from-seed/{seed_id}").json()

    assert reentered["id"] == first["id"]
    assert reentered["is_listener_active"] is True
    assert reentered["is_playing"] is True
