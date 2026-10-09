"""The owner can see which evidence stood behind each chapter's narration."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import services.api.main as api_module

app = api_module.app
HEADERS = {"X-Wavecast-Listener": "evidence-listener"}


def _create(client: TestClient) -> dict:
    return client.post("/api/episodes/from-seed/city-pop-misunderstood", headers=HEADERS).json()


def _session(*, cited: list[str]) -> SimpleNamespace:
    def evidence(identifier: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=identifier,
            claim_or_excerpt=f"claim {identifier} " + "x" * 600,
            source_domain="example.org",
            source_title="A page",
            source_provider="tavily",
            confidence=0.8,
            source_url="https://example.org/secret-path?token=abc",
            query="private query",
        )

    return SimpleNamespace(
        unfulfilled_artists=[],
        chapters=[
            SimpleNamespace(chapter_id="chapter-1", chapter=SimpleNamespace(evidence_ids=cited)),
            SimpleNamespace(chapter_id="chapter-2", chapter=SimpleNamespace(evidence_ids=[])),
        ],
        research=SimpleNamespace(evidence=[evidence("e1"), evidence("e2"), evidence("e3")]),
    )


def test_an_episode_without_a_stored_plan_has_no_evidence() -> None:
    client = TestClient(app)
    created = _create(client)

    response = client.get(f"/api/episodes/{created['id']}/evidence", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {"episode_id": created["id"], "chapters": [], "evidence": []}


def test_only_cited_evidence_is_listed_without_urls_or_queries(monkeypatch) -> None:
    client = TestClient(app)
    created = _create(client)
    episode = api_module.orchestrator.get(created["id"])
    episode.progressive_session = _session(cited=["e1", "e3"])
    monkeypatch.setattr(api_module.orchestrator, "get", lambda _id: episode)

    body = client.get(f"/api/episodes/{created['id']}/evidence", headers=HEADERS).json()

    assert [item["id"] for item in body["evidence"]] == ["e1", "e3"]
    assert body["chapters"][0]["evidence_ids"] == ["e1", "e3"]
    assert body["chapters"][1]["evidence_ids"] == []
    first = body["evidence"][0]
    assert len(first["claim"]) == 400
    assert first["source_domain"] == "example.org"
    assert set(first) == {"id", "claim", "source_domain", "source_title", "source_provider", "confidence"}
    assert "secret-path" not in str(body) and "private query" not in str(body)


def test_another_listener_cannot_read_the_evidence() -> None:
    client = TestClient(app)
    created = _create(client)

    response = client.get(
        f"/api/episodes/{created['id']}/evidence", headers={"X-Wavecast-Listener": "someone-else"}
    )

    assert response.status_code in (403, 404)
