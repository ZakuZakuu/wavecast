from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.proposals import (
    InMemoryProgramProposalRepository,
    ProgramProposal,
    ProgramProposalGenerationError,
    ProposalGenerationRequest,
)
from wavecast.storage.library import InMemoryUserLibraryRepository
from wavecast.storage.quota import (
    InMemoryGenerationQuotaRepository,
    QuotaExceededError,
)

from services.api import main as api_module


class FakeVerifier:
    async def verify(self, token: str) -> str:
        if token not in {"token-a", "token-b"}:
            raise ValueError("bad token")
        return "user-a" if token == "token-a" else "user-b"


class CountingGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def generate(self, request: ProposalGenerationRequest) -> list[ProgramProposal]:
        self.calls += 1
        if self.fail:
            self.fail = False
            raise ProgramProposalGenerationError("test_failure")
        template = ProgramProposal.from_episode_seed(api_module.SEEDS[0])
        return [
            template.model_copy(
                update={
                    "id": f"quota-proposal-{self.calls}-{index}",
                    "title": f"Quota Program {self.calls}-{index}",
                    "topic": request.prompt,
                }
            )
            for index in range(request.count)
        ]


def install_api(monkeypatch, generator: CountingGenerator) -> None:
    repo = InMemoryEpisodeRepository()
    monkeypatch.setattr(api_module, "repository", repo)
    monkeypatch.setattr(api_module, "orchestrator", EpisodeOrchestrator(repo))
    monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
    monkeypatch.setattr(api_module, "user_library_repository", InMemoryUserLibraryRepository())
    monkeypatch.setattr(api_module, "generation_quota_repository", InMemoryGenerationQuotaRepository())
    monkeypatch.setattr(api_module, "proposal_generator", generator)
    monkeypatch.setattr(api_module, "_auth_verifier", FakeVerifier())


def proposal_request(prompt: str, *, count: int = 1) -> dict[str, object]:
    return {"prompt": prompt, "duration_intent": "SHORT", "count": count}


def test_guest_quota_reserves_before_generation_and_releases_provider_failure(monkeypatch) -> None:
    generator = CountingGenerator()
    install_api(monkeypatch, generator)
    monkeypatch.setattr(api_module, "GUEST_PROGRAM_LIMIT", 3)
    monkeypatch.setattr(api_module, "GLOBAL_DAILY_PROGRAM_LIMIT", 20)
    client = TestClient(api_module.app)
    headers = {"X-Wavecast-Listener": "quota-listener"}

    generator.fail = True
    failed = client.post("/api/program-proposals", json=proposal_request("first failure"), headers=headers)
    assert failed.status_code == 502
    assert generator.calls == 1

    for number in range(3):
        created = client.post(
            "/api/program-proposals",
            json=proposal_request(f"successful program {number}"),
            headers=headers,
        )
        assert created.status_code == 200

    rejected = client.post(
        "/api/program-proposals",
        json=proposal_request("must be rejected before generator"),
        headers=headers,
    )
    assert rejected.status_code == 429
    assert "访客可以先创建 3 档节目" in rejected.json()["detail"]
    assert generator.calls == 4


def test_global_daily_limit_applies_across_distinct_guest_listeners(monkeypatch) -> None:
    generator = CountingGenerator()
    install_api(monkeypatch, generator)
    monkeypatch.setattr(api_module, "GUEST_PROGRAM_LIMIT", 3)
    monkeypatch.setattr(api_module, "GLOBAL_DAILY_PROGRAM_LIMIT", 1)
    client = TestClient(api_module.app)

    first = client.post(
        "/api/program-proposals",
        json=proposal_request("first listener"),
        headers={"X-Wavecast-Listener": "global-listener-one"},
    )
    second = client.post(
        "/api/program-proposals",
        json=proposal_request("second listener"),
        headers={"X-Wavecast-Listener": "global-listener-two"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert "服务已达到使用上限" in second.json()["detail"]
    assert generator.calls == 1


def test_authenticated_proposal_creation_is_owned_and_added_to_cloud_library(monkeypatch) -> None:
    generator = CountingGenerator()
    install_api(monkeypatch, generator)
    client = TestClient(api_module.app)
    headers = {
        "X-Wavecast-Listener": "account-proposal-device-a",
        "Authorization": "Bearer token-a",
    }

    created = client.post(
        "/api/program-proposals",
        json=proposal_request("account proposal"),
        headers=headers,
    )
    assert created.status_code == 200
    proposal_id = created.json()["proposals"][0]["id"]
    library = client.get("/api/me/library", headers=headers)
    assert library.status_code == 200
    assert library.json()["createdProgramIds"] == [proposal_id]
    assert client.get(
        f"/api/programs/{proposal_id}",
        headers={
            "X-Wavecast-Listener": "account-proposal-device-b",
            "Authorization": "Bearer token-a",
        },
    ).status_code == 200
    assert client.get(
        f"/api/programs/{proposal_id}",
        headers={
            "X-Wavecast-Listener": "other-account-device",
            "Authorization": "Bearer token-b",
        },
    ).status_code == 404


def test_guest_multi_count_is_rejected_before_provider_when_over_limit(monkeypatch) -> None:
    generator = CountingGenerator()
    install_api(monkeypatch, generator)
    monkeypatch.setattr(api_module, "GUEST_PROGRAM_LIMIT", 3)
    client = TestClient(api_module.app)

    response = client.post(
        "/api/program-proposals",
        json=proposal_request("too many programs", count=4),
        headers={"X-Wavecast-Listener": "quota-count-listener"},
    )

    assert response.status_code == 429
    assert generator.calls == 0


def test_guest_proposal_episode_merge_is_idempotent_and_claims_only_listener_owned_items(monkeypatch) -> None:
    generator = CountingGenerator()
    install_api(monkeypatch, generator)
    client = TestClient(api_module.app)
    guest_headers = {"X-Wavecast-Listener": "guest-merge-listener"}

    created = client.post(
        "/api/program-proposals",
        json=proposal_request("my guest program"),
        headers=guest_headers,
    )
    assert created.status_code == 200
    proposal_id = created.json()["proposals"][0]["id"]
    episode = client.post(f"/api/episodes/from-seed/{proposal_id}", headers=guest_headers).json()

    stranger = ProgramProposal.from_episode_seed(api_module.SEEDS[1]).model_copy(
        update={"id": "not-this-listeners-proposal"}
    )
    api_module.proposal_repository.save_many(
        [stranger], owner_listener_id="different-listener", source="tune"
    )
    stranger_episode = api_module.orchestrator.start_or_resume(
        api_module.SEEDS[1], "different-listener"
    )

    auth_headers = {
        "X-Wavecast-Listener": "guest-merge-listener",
        "Authorization": "Bearer token-a",
    }
    local_library = {
        "version": 1,
        "favoriteSeedIds": [proposal_id, stranger.id],
        "createdProgramIds": [proposal_id, stranger.id],
        "recentPrograms": [{
            "episodeId": episode["id"],
            "seedId": proposal_id,
            "title": "client title is ignored",
            "topic": None,
            "currentTitle": None,
            "updatedAt": 1000,
            "progressSeconds": 0,
            "durationSeconds": 1,
        }],
        "savedEpisodes": [],
    }
    first = client.post(
        "/api/me/library/merge", json={"library": local_library}, headers=auth_headers
    )
    second = client.post(
        "/api/me/library/merge", json={"library": local_library}, headers=auth_headers
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["favoriteSeedIds"] == [proposal_id]
    assert first.json()["createdProgramIds"] == [proposal_id]
    assert first.json()["recentPrograms"][0]["title"] == episode["title"]

    device_b = {"Authorization": "Bearer token-a", "X-Wavecast-Listener": "device-b"}
    assert client.get(f"/api/programs/{proposal_id}", headers=device_b).status_code == 200
    from_account = client.get(f"/api/episodes/{episode['id']}", headers=device_b)
    assert from_account.status_code == 200
    assert "owner_user_id" not in from_account.json()

    resumed = client.post(f"/api/episodes/from-seed/{proposal_id}", headers=device_b)
    assert resumed.status_code == 200
    assert resumed.json()["id"] == episode["id"]

    assert client.get(f"/api/programs/{stranger.id}", headers=device_b).status_code == 404
    assert client.get(
        f"/api/episodes/{stranger_episode.id}",
        headers={"Authorization": "Bearer token-a", "X-Wavecast-Listener": "device-b"},
    ).status_code == 404

    other_user = {"Authorization": "Bearer token-b", "X-Wavecast-Listener": "device-c"}
    assert client.get(f"/api/episodes/{episode['id']}", headers=other_user).status_code == 404


def test_proposal_id_conflict_cannot_transfer_owner() -> None:
    proposals = InMemoryProgramProposalRepository()
    owned = ProgramProposal.from_episode_seed(api_module.SEEDS[0]).model_copy(
        update={"id": "stable-private-proposal"}
    )
    proposals.save_many([owned], owner_listener_id="owner-device", owner_user_id="owner-account")
    with pytest.raises(RuntimeError, match="proposal id already exists"):
        proposals.save_many(
            [owned.model_copy(update={"title": "attacker replacement"})],
            owner_listener_id="attacker-device",
            owner_user_id="attacker-account",
        )
    assert proposals.get("stable-private-proposal") == owned
    assert proposals.get_owner("stable-private-proposal") == ("owner-device", "owner-account")


def test_authenticated_recent_write_claims_current_listener_episode(monkeypatch) -> None:
    generator = CountingGenerator()
    install_api(monkeypatch, generator)
    client = TestClient(api_module.app)
    listener_id = "recent-claim-listener"
    episode = client.post(
        "/api/episodes/from-seed/city-pop-misunderstood",
        headers={"X-Wavecast-Listener": listener_id},
    ).json()
    response = client.put(
        f"/api/me/library/recents/{episode['id']}",
        headers={
            "X-Wavecast-Listener": listener_id,
            "Authorization": "Bearer token-a",
        },
        json={
            "episodeId": episode["id"],
            "seedId": episode["seed_id"],
            "title": "client title",
            "topic": None,
            "currentTitle": None,
            "updatedAt": 10,
            "progressSeconds": 0,
            "durationSeconds": 100,
        },
    )
    assert response.status_code == 200
    assert api_module.repository.get(episode["id"]).owner_user_id == "user-a"
    assert client.get(
        f"/api/episodes/{episode['id']}",
        headers={"X-Wavecast-Listener": "device-b", "Authorization": "Bearer token-a"},
    ).status_code == 200


def test_cloud_library_requires_authenticated_principal() -> None:
    client = TestClient(api_module.app)
    response = client.get("/api/me/library", headers={"X-Wavecast-Listener": "guest-only"})
    assert response.status_code == 401


def test_quota_charge_identity_is_idempotent() -> None:
    quota = InMemoryGenerationQuotaRepository()
    limits = {"guest_limit": 2, "auth_daily_limit": 10, "global_daily_limit": 10}
    first = quota.reserve("idempotent-listener", None, 1, **limits)
    quota.charge(first, ["same-program-id"])
    second = quota.reserve("idempotent-listener", None, 1, **limits)
    quota.charge(second, ["same-program-id"])
    third = quota.reserve("idempotent-listener", None, 1, **limits)
    quota.charge(third, ["different-program-id"])
    with pytest.raises(QuotaExceededError, match="guest_limit"):
        quota.reserve("idempotent-listener", None, 1, **limits)

def test_authenticated_daily_limit_is_user_scoped_and_configurable(monkeypatch) -> None:
    generator = CountingGenerator()
    install_api(monkeypatch, generator)
    monkeypatch.setattr(api_module, "AUTH_DAILY_PROGRAM_LIMIT", 1)
    monkeypatch.setattr(api_module, "GLOBAL_DAILY_PROGRAM_LIMIT", 20)
    client = TestClient(api_module.app)
    first = client.post(
        "/api/program-proposals",
        json=proposal_request("account one"),
        headers={"X-Wavecast-Listener": "device-one", "Authorization": "Bearer token-a"},
    )
    second = client.post(
        "/api/program-proposals",
        json=proposal_request("account two"),
        headers={"X-Wavecast-Listener": "device-two", "Authorization": "Bearer token-a"},
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert "明天再试" in second.json()["detail"]
    assert generator.calls == 1


def test_library_merge_uses_union_and_newest_recent_and_saved_payload() -> None:
    library = InMemoryUserLibraryRepository()
    initial = library.merge("merge-user", {
        "favoriteSeedIds": ["favorite-a"],
        "createdProgramIds": ["created-a"],
        "recentPrograms": [{
            "episodeId": "episode-a", "seedId": "seed-a", "title": "old",
            "topic": None, "currentTitle": "old chapter", "updatedAt": 10,
            "progressSeconds": 10, "durationSeconds": 100,
        }],
        "savedEpisodes": [{
            "episodeId": "episode-b", "seedId": "seed-b", "title": "saved old",
            "topic": None, "currentTitle": None, "updatedAt": 10,
            "progressSeconds": 0, "durationSeconds": 100, "savedAt": 10,
        }],
    })
    newer = library.merge("merge-user", {
        "favoriteSeedIds": ["favorite-b"],
        "createdProgramIds": ["created-b"],
        "recentPrograms": [{
            "episodeId": "episode-a", "seedId": "seed-a", "title": "new",
            "topic": None, "currentTitle": "new chapter", "updatedAt": 20,
            "progressSeconds": 20, "durationSeconds": 100,
        }],
        "savedEpisodes": [{
            "episodeId": "episode-b", "seedId": "seed-b", "title": "saved new",
            "topic": None, "currentTitle": None, "updatedAt": 20,
            "progressSeconds": 0, "durationSeconds": 100, "savedAt": 20,
        }],
    })
    stale = library.merge("merge-user", {
        "recentPrograms": [{
            "episodeId": "episode-a", "seedId": "seed-a", "title": "stale",
            "topic": None, "currentTitle": None, "updatedAt": 5,
            "progressSeconds": 1, "durationSeconds": 100,
        }],
        "savedEpisodes": [{
            "episodeId": "episode-b", "seedId": "seed-b", "title": "stale saved",
            "topic": None, "currentTitle": None, "updatedAt": 5,
            "progressSeconds": 0, "durationSeconds": 100, "savedAt": 5,
        }],
    })
    assert initial["favoriteSeedIds"] == ["favorite-a"]
    assert newer["favoriteSeedIds"] == ["favorite-a", "favorite-b"]
    assert newer["createdProgramIds"] == ["created-a", "created-b"]
    assert stale["recentPrograms"][0]["title"] == "new"
    assert stale["savedEpisodes"][0]["title"] == "saved new"
