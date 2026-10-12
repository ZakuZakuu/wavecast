import pytest
from fastapi.testclient import TestClient
from wavecast.proposals import InMemoryProgramProposalRepository

from services.api import main as api_module

OWNER = {"X-Wavecast-Listener": "share-owner-listener"}
VISITOR = {"X-Wavecast-Listener": "share-visitor-listener"}


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
    client = TestClient(api_module.app)
    created = client.post(
        "/api/program-proposals",
        json={"prompt": "下雨的夜晚，想听温柔的爵士", "duration_intent": "SHORT", "count": 1},
        headers=OWNER,
    )
    assert created.status_code == 200
    return client, created.json()["proposals"][0]


def test_anyone_with_the_link_sees_the_promise_but_not_the_prompt(shared) -> None:
    client, proposal = shared

    response = client.get(f"/api/programs/{proposal['id']}/public", headers=VISITOR)

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == proposal["title"]
    assert body["description"] == proposal["short_description"]
    assert body["route"] == proposal["editorial_route"]
    assert body["is_owner"] is False
    assert "topic" not in body
    assert "taste_context" not in body
    # The owner is recognised, so the page can offer "back" instead of "log in".
    assert client.get(f"/api/programs/{proposal['id']}/public", headers=OWNER).json()["is_owner"] is True


def test_unknown_link_is_a_plain_not_found(shared) -> None:
    client, _ = shared
    assert client.get("/api/programs/proposal-nope/public").status_code == 404
    assert client.post("/api/programs/proposal-nope/adopt", headers=VISITOR).status_code == 404


def test_built_in_programmes_are_public_and_have_no_made_up_outline() -> None:
    client = TestClient(api_module.app)
    body = client.get("/api/programs/city-pop-misunderstood/public").json()
    assert body["route"] == []
    assert body["is_owner"] is True  # nothing to copy: anyone can play a built-in programme


def test_adopting_gives_the_visitor_their_own_copy_once(shared) -> None:
    client, proposal = shared

    first = client.post(f"/api/programs/{proposal['id']}/adopt", headers=VISITOR)

    assert first.status_code == 200
    copy = first.json()
    assert copy["id"] != proposal["id"]
    assert copy["title"] == proposal["title"]
    assert client.get(f"/api/programs/{copy['id']}", headers=VISITOR).status_code == 200
    # The original stays the owner's; the visitor never gains access to it.
    assert client.get(f"/api/programs/{proposal['id']}", headers=VISITOR).status_code == 404
    # Adopting your own programme (or a copy you hold) spends nothing and returns it.
    again = client.post(f"/api/programs/{copy['id']}/adopt", headers=VISITOR)
    assert again.json()["id"] == copy["id"]
    mine = client.post(f"/api/programs/{proposal['id']}/adopt", headers=OWNER)
    assert mine.json()["id"] == proposal["id"]
    # The copy starts a normal episode.
    started = client.post(f"/api/episodes/from-seed/{copy['id']}", headers=VISITOR)
    assert started.status_code == 200


def test_a_short_code_finds_the_programme_and_nothing_else(shared) -> None:
    client, proposal = shared
    code = proposal["id"].removeprefix("proposal-")[:10]

    found = client.get(f"/api/programs/by-code/{code}")
    assert found.status_code == 200
    assert found.json() == {"id": proposal["id"]}

    assert client.get("/api/programs/by-code/0000000000").status_code == 404
    # Only the exact short form is accepted: no prefixes of other lengths, no patterns.
    assert client.get(f"/api/programs/by-code/{code[:6]}").status_code == 404
    assert client.get("/api/programs/by-code/%25%25%25%25%25%25%25%25%25%25").status_code == 404


def test_a_short_code_matching_two_programmes_is_not_guessed(shared) -> None:
    client, proposal = shared
    from wavecast.proposals import InMemoryProgramProposalRepository

    repository = InMemoryProgramProposalRepository()
    first = proposal["id"]
    twin = first[:19] + ("0" if first[19] != "0" else "1") + first[20:]
    for pid in (first, twin):
        repository.save_many([api_module.ProgramProposal(**{**proposal, "id": pid})], owner_listener_id="x")
    assert repository.find_id_by_prefix(first[:19]) is None
    assert repository.find_id_by_prefix(first[:25]) == first
