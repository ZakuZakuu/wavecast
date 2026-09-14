from fastapi.testclient import TestClient

from services.api.main import app


def test_mock_vertical_slice_from_seed_to_materialized_resumeable_episode() -> None:
    client = TestClient(app)
    seeds = client.get("/api/seeds").json()
    assert seeds

    created = client.post(f"/api/episodes/from-seed/{seeds[0]['id']}")
    assert created.status_code == 200
    episode = created.json()
    episode_id = episode["id"]
    assert episode["generated_frontier_seconds"] == 22

    assert (
        client.post(f"/api/episodes/{episode_id}/seek", json={"position_seconds": 10}).status_code
        == 200
    )
    too_far = client.post(f"/api/episodes/{episode_id}/seek", json={"position_seconds": 23})
    assert too_far.status_code == 409

    next_response = client.post(f"/api/episodes/{episode_id}/next")
    assert next_response.status_code == 200
    assert next_response.json()["current_segment_id"] == "segment-bridge"

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
