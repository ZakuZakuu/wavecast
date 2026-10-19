"""A finished programme shared as itself: published once, played by every listener's own copy."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from wavecast.full_version import full_version_status
from wavecast.orchestration.worker import GenerationWorker
from wavecast.proposals import InMemoryProgramProposalRepository
from wavecast.publication_service import PublicationService
from wavecast.publishing import PublicationStatus
from wavecast.rendering import ProgramRenderChunk, ProgramRenderManifest
from wavecast.rendering.programme import manifest_key
from wavecast.storage import (
    InMemoryGenerationJobRepository,
    InMemoryPublicationRepository,
    LocalObjectStorageProvider,
)

import services.api.main as api_module

DURATION = 60.0


class Rig:
    def __init__(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.storage = LocalObjectStorageProvider(tmp_path)
        self.jobs = InMemoryGenerationJobRepository()
        self.publications = InMemoryPublicationRepository()
        self.free: int | None = 10 * 1024**3
        monkeypatch.setattr(api_module, "audio_storage", self.storage)
        monkeypatch.setattr(api_module, "generation_job_repository", self.jobs)
        monkeypatch.setattr(api_module, "publication_repository", self.publications)
        monkeypatch.setattr(api_module, "proposal_repository", InMemoryProgramProposalRepository())
        monkeypatch.setattr(
            api_module, "generation_worker",
            GenerationWorker(self.jobs, api_module.orchestrator, worker_id="publish-test"),
        )
        monkeypatch.setattr(api_module, "TAKEN_DOWN_PROGRAMMES", frozenset())
        monkeypatch.setattr(api_module, "_render_programme", self.render)
        self.service = PublicationService(
            repository=self.publications,
            episode=lambda episode_id: api_module.orchestrator.get(episode_id),
            mark_published=lambda episode_id: api_module._mark_episode_published(episode_id),
            render=lambda episode_id, step: api_module._render_programme(episode_id, step),
            plan_info=lambda _id: (DURATION, "fingerprint"),
            full_state=lambda episode: full_version_status(
                episode, self.jobs.get_for_episode(episode.id), datetime.now(UTC),
            ),
            storage=self.storage,
            free_bytes=lambda: self.free,
            budget_bytes=lambda: 10 * 1024**3,
            snapshot_for=lambda episode: api_module._publication_snapshot(episode),
            taken_down=lambda publication_id: publication_id in api_module.TAKEN_DOWN_PROGRAMMES,
        )
        monkeypatch.setattr(api_module, "publication_service", self.service)

    async def render(self, episode_id: str, step: float | None = None) -> ProgramRenderManifest:
        chunks = []
        for index in range(10):
            content = f"{episode_id}-{index}".encode() * 8
            key = f"program-renders/{episode_id}/chunk-{index}.aac"
            await self.storage.put(key, content, "audio/aac")
            chunks.append(ProgramRenderChunk(
                index=index, start_seconds=index * 6.0, duration_seconds=6.0, plan_fingerprint="fingerprint",
                content_sha256=hashlib.sha256(content).hexdigest(), asset_key=key,
                audio_url=f"/api/assets/audio/{key}",
            ))
        manifest = ProgramRenderManifest(
            episode_id=episode_id, chunk_duration_seconds=6, holdback_seconds=30,
            rendered_frontier_seconds=DURATION, complete=True, chunks=tuple(chunks),
            stream_url=f"/api/program-streams/{episode_id}.m3u8",
        )
        await self.storage.put(manifest_key(episode_id), manifest.model_dump_json().encode(), "application/json")
        return manifest


@pytest.fixture
def rig(tmp_path, monkeypatch) -> Rig:
    return Rig(tmp_path, monkeypatch)


@pytest.fixture
def client(rig):
    with TestClient(api_module.app) as test_client:
        yield test_client


def who() -> dict[str, str]:
    return {"X-Wavecast-Listener": f"published-{uuid4().hex}"}


def finished_episode(client: TestClient, owner: dict[str, str]) -> dict:
    """A programme of the owner's, with its 完整版 made."""
    accepted = client.post(
        "/api/full-versions",
        json={"prompt": f"一档要分享的节目 {uuid4().hex}", "duration_intent": "SHORT", "count": 1},
        headers=owner,
    )
    assert accepted.status_code == 202
    request_id = accepted.json()["request_id"]
    for _ in range(200):
        [item] = client.get("/api/full-versions/requests", params={"ids": request_id}, headers=owner).json()
        if item["status"] != "creating":
            break
        time.sleep(0.05)
    assert item["status"] == "ready", item
    assert asyncio.run(api_module.generation_worker.run_once()) is True
    return item


def publish(client: TestClient, owner: dict[str, str], episode_id: str, visibility: str = "link") -> dict:
    response = client.post(f"/api/episodes/{episode_id}/publish", json={"visibility": visibility}, headers=owner)
    assert response.status_code == 202, response.text
    return response.json()


def published(client: TestClient, owner: dict[str, str], episode_id: str, visibility: str = "link") -> dict:
    item = publish(client, owner, episode_id, visibility)
    for _ in range(200):
        [item] = client.get("/api/publications", params={"episode_ids": episode_id}, headers=owner).json()
        if item["status"] not in {"preparing", "mixing"}:
            break
        time.sleep(0.05)
    assert item["status"] == "published", item
    return item


def test_publishing_mixes_once_and_goes_live_with_a_link_anyone_can_open(client, rig) -> None:
    owner = who()
    made = finished_episode(client, owner)

    accepted = publish(client, owner, made["episode_id"], "public")
    assert accepted["status"] in {"mixing", "published"} and accepted["visibility"] == "public"
    item = published(client, owner, made["episode_id"])

    assert item["progress"] == 100 and item["id"].startswith("pub-")
    visitor = who()
    resolved = client.get(f"/api/programs/by-code/{item['code']}")
    assert resolved.json() == {"id": item["id"]}
    page = client.get(f"/api/programs/{item['id']}/public", headers=visitor).json()
    assert page["published"] is True and page["revoked"] is False and page["is_owner"] is False
    assert "topic" not in page
    assert client.get(f"/api/programs/{item['id']}/public", headers=owner).json()["is_owner"] is True
    # The source episode is frozen: what the copies play can no longer change.
    assert client.get(f"/api/episodes/{made['episode_id']}", headers=owner).json()["state"] == "PUBLISHED"


def test_a_listeners_copy_plays_the_fixed_feed_with_its_own_progress(client, rig) -> None:
    owner, visitor, other = who(), who(), who()
    made = finished_episode(client, owner)
    item = published(client, owner, made["episode_id"])

    copy = client.post(f"/api/published/{item['id']}/copy", headers=visitor)
    assert copy.status_code == 200
    body = copy.json()
    assert body["seed_id"] == item["id"] and body["published_programme_id"] == item["id"]
    assert body["state"] == "PUBLISHED" and body["id"] != made["episode_id"]
    # What the sharer typed is not in it; the copy is named by what the link promised.
    assert body["topic"] == body["title"]
    # One copy per listener and programme.
    assert client.post(f"/api/published/{item['id']}/copy", headers=visitor).json()["id"] == body["id"]
    assert client.post(f"/api/published/{item['id']}/copy", headers=other).json()["id"] != body["id"]

    # The copy plays the source's feed as it is: nothing is rendered for it.
    feed = client.post(f"/api/episodes/{body['id']}/program-render", headers=visitor)
    assert feed.status_code == 200
    assert feed.json()["episodeId"] == made["episode_id"] and feed.json()["complete"] is True
    assert client.get(f"/api/episodes/{body['id']}/program-render", headers=visitor).json() == feed.json()
    # Progress is the copy's own.
    client.post(f"/api/episodes/{body['id']}/program-playback-checkpoint", json={"position_seconds": 21}, headers=visitor)
    assert client.get(f"/api/episodes/{body['id']}", headers=visitor).json()["program_playback_position_seconds"] == 21
    assert client.get(f"/api/episodes/{made['episode_id']}", headers=owner).json()["program_playback_position_seconds"] == 0
    # Nobody else can read or drive it, and it cannot be re-mixed or exported.
    assert client.get(f"/api/episodes/{body['id']}", headers=other).status_code == 404
    assert client.post(f"/api/episodes/{body['id']}/mixdown", headers=visitor).status_code == 409
    assert client.post(f"/api/episodes/{body['id']}/prepare-mixdown", headers=visitor).status_code == 409
    # Nothing was spent: no allowance, no generation job.
    assert api_module.generation_job_repository.get_for_episode(body["id"]) is None


def test_revoking_stops_new_copies_but_not_the_ones_that_exist(client, rig) -> None:
    owner, holder, late = who(), who(), who()
    made = finished_episode(client, owner)
    item = published(client, owner, made["episode_id"])
    copy = client.post(f"/api/published/{item['id']}/copy", headers=holder).json()

    revoked = client.post(f"/api/publications/{item['id']}/revoke", headers=owner)
    assert revoked.json()["status"] == "revoked"

    # A new visitor is told it is no longer shared; nothing is created for them.
    assert client.get(f"/api/programs/{item['id']}/public", headers=late).status_code == 410
    assert client.get(f"/api/programs/{item['id']}/public", headers=late).json()["detail"] == "revoked"
    assert client.post(f"/api/published/{item['id']}/copy", headers=late).status_code == 410
    # Whoever holds a copy keeps listening, and can still open the page.
    assert client.get(f"/api/programs/{item['id']}/public", headers=holder).json()["revoked"] is True
    assert client.post(f"/api/published/{item['id']}/copy", headers=holder).json()["id"] == copy["id"]
    assert client.post(f"/api/episodes/{copy['id']}/program-render", headers=holder).status_code == 200
    # The audio is not reclaimed because it was revoked.
    assert made["episode_id"] in rig.publications.pinned_episode_ids()

    restored = client.post(f"/api/publications/{item['id']}/restore", headers=owner)
    assert restored.json()["status"] == "published"
    assert client.post(f"/api/published/{item['id']}/copy", headers=late).status_code == 200


def test_only_the_owner_manages_a_publication(client, rig) -> None:
    owner, stranger = who(), who()
    made = finished_episode(client, owner)
    item = published(client, owner, made["episode_id"])

    assert client.post(f"/api/episodes/{made['episode_id']}/publish", json={}, headers=stranger).status_code == 404
    assert client.post(f"/api/publications/{item['id']}/revoke", headers=stranger).status_code == 404
    assert client.post(
        f"/api/publications/{item['id']}/visibility", json={"visibility": "public"}, headers=stranger,
    ).status_code == 404
    assert client.get("/api/publications", params={"episode_ids": made["episode_id"]}, headers=stranger).json() == []
    # A copy is not the sharer's to publish again.
    copy = client.post(f"/api/published/{item['id']}/copy", headers=stranger).json()
    assert client.post(f"/api/episodes/{copy['id']}/publish", json={}, headers=stranger).status_code == 409

    changed = client.post(
        f"/api/publications/{item['id']}/visibility", json={"visibility": "public"}, headers=owner,
    )
    assert changed.json()["visibility"] == "public"


def test_old_links_that_made_a_fresh_copy_per_visitor_no_longer_open(client, rig) -> None:
    owner, visitor = who(), who()
    made = finished_episode(client, owner)
    proposal_id = made["programme_id"]
    code = proposal_id.removeprefix("proposal-")[:10]

    page = client.get(f"/api/programs/{proposal_id}/public", headers=visitor)
    assert (page.status_code, page.json()["detail"]) == (410, "legacy")
    assert client.post(f"/api/programs/{proposal_id}/adopt", headers=visitor).status_code == 410
    resolved = client.get(f"/api/programs/by-code/{code}")
    assert (resolved.status_code, resolved.json()["detail"]) == (410, "legacy")
    # The owner still sees their own programme, and nothing else is guessed.
    assert client.get(f"/api/programs/{proposal_id}/public", headers=owner).json()["is_owner"] is True
    assert client.get("/api/programs/by-code/0000000000").status_code == 404
    assert client.get("/api/programs/by-code/%25%25%25%25%25%25%25%25%25%25").status_code == 404
    assert client.get("/api/programs/pub-nope/public").status_code == 404


def test_a_programme_still_being_made_is_not_open_to_anyone_else(client, rig) -> None:
    owner, visitor = who(), who()
    accepted = client.post(
        "/api/full-versions",
        json={"prompt": f"还没做完的节目 {uuid4().hex}", "duration_intent": "SHORT", "count": 1},
        headers=owner,
    )
    request_id = accepted.json()["request_id"]
    for _ in range(200):
        [made] = client.get("/api/full-versions/requests", params={"ids": request_id}, headers=owner).json()
        if made["status"] != "creating":
            break
        time.sleep(0.05)
    # The worker has not made the 完整版: publishing waits for it.
    item = publish(client, owner, made["episode_id"])
    assert item["status"] == "preparing" and item["step"] == "full"
    assert client.get(f"/api/programs/{item['id']}/public", headers=visitor).status_code == 404
    assert client.post(f"/api/published/{item['id']}/copy", headers=visitor).status_code == 404
    assert client.get(f"/api/programs/by-code/{item['code']}").json() == {"id": item["id"]}

    assert asyncio.run(api_module.generation_worker.run_once()) is True
    [after] = client.get("/api/publications", params={"episode_ids": made["episode_id"]}, headers=owner).json()
    for _ in range(200):
        if after["status"] == "published":
            break
        time.sleep(0.05)
        [after] = client.get("/api/publications", params={"episode_ids": made["episode_id"]}, headers=owner).json()
    assert after["status"] == "published"
    assert client.post(f"/api/published/{item['id']}/copy", headers=visitor).status_code == 200


def test_publishing_is_refused_without_room_and_says_so(client, rig) -> None:
    owner = who()
    made = finished_episode(client, owner)
    rig.free = 80 * 1024 * 1024

    refused = client.post(f"/api/episodes/{made['episode_id']}/publish", json={}, headers=owner)

    assert refused.status_code == 503 and refused.headers["x-wavecast-refusal"] == "space"
    assert client.get("/api/publications", params={"episode_ids": made["episode_id"]}, headers=owner).json() == []


def test_a_programme_switched_off_by_hand_stops_playing(client, rig, monkeypatch) -> None:
    owner, holder, late = who(), who(), who()
    made = finished_episode(client, owner)
    item = published(client, owner, made["episode_id"])
    copy = client.post(f"/api/published/{item['id']}/copy", headers=holder).json()

    monkeypatch.setattr(api_module, "TAKEN_DOWN_PROGRAMMES", frozenset({item["id"]}))

    assert client.get(f"/api/programs/{item['id']}/public", headers=late).status_code == 404
    assert client.post(f"/api/published/{item['id']}/copy", headers=late).status_code == 404
    assert client.post(f"/api/published/{item['id']}/copy", headers=holder).status_code == 404
    assert client.post(f"/api/episodes/{copy['id']}/program-render", headers=holder).status_code == 404
    assert client.get(f"/api/program-streams/{made['episode_id']}.m3u8").status_code == 404


def test_listens_are_counted_once_per_listener(client, rig) -> None:
    owner, visitor = who(), who()
    made = finished_episode(client, owner)
    item = published(client, owner, made["episode_id"])

    for _ in range(3):
        assert client.post(f"/api/published/{item['id']}/listen", headers=visitor).status_code == 204
    assert client.post(f"/api/published/{item['id']}/listen", headers=who()).status_code == 204

    assert rig.publications.listen_count(item["id"]) == 2


def test_published_audio_is_never_reclaimed_by_the_cache_cleanup(tmp_path, monkeypatch) -> None:
    root = tmp_path / "audio"
    for name in ("kept", "other"):
        (root / "program-renders" / name).mkdir(parents=True)
        (root / "program-renders" / name / "chunk.aac").write_bytes(b"x" * 10)
    publications = InMemoryPublicationRepository()
    from wavecast.models.episode import CoverParams
    from wavecast.publishing import ProgrammeSnapshot, Publication, new_publication_id, short_code

    identifier = new_publication_id()
    now = datetime.now(UTC)
    publications.create(Publication(
        id=identifier, code=short_code(identifier), source_episode_id="kept", owner_listener_id="o",
        status=PublicationStatus.REVOKED, published_at=now, created_at=now, updated_at=now,
        programme=ProgrammeSnapshot(
            title="t", description="d", estimated_duration_seconds=60, opening_track_title="s",
            opening_track_artist="a", cover=CoverParams(family="f", seed=1, palette=("#000000", "#ffffff")),
        ),
    ))
    monkeypatch.setattr(api_module, "publication_repository", publications)
    monkeypatch.setattr(api_module, "AUDIO_ROOT", str(root))
    monkeypatch.setattr(api_module, "PROGRAM_RENDER_GC_LOW_WATERMARK_BYTES", 100)
    monkeypatch.setattr(api_module, "PROGRAM_RENDER_GC_TARGET_FREE_BYTES", 200)
    monkeypatch.setattr(
        api_module.shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(1000, 950, 50),
    )

    api_module._gc_program_render_cache("current")

    assert (root / "program-renders" / "kept").exists()
    assert not (root / "program-renders" / "other").exists()


def test_a_programme_never_played_can_be_published_from_its_page(client, rig) -> None:
    owner, visitor = who(), who()
    proposals = client.post(
        "/api/program-proposals",
        json={"prompt": f"还没听过的节目 {uuid4().hex}", "duration_intent": "SHORT", "count": 1},
        headers=owner,
    )
    programme_id = proposals.json()["proposals"][0]["id"]
    assert client.get(f"/api/programs/{programme_id}/publication", headers=owner).status_code == 404

    item = client.post(f"/api/programs/{programme_id}/publish", json={"visibility": "link"}, headers=owner)
    assert item.status_code == 202 and item.json()["status"] == "preparing"
    # Asked again, it is the same publication, and nobody is made to start the programme twice.
    again = client.post(f"/api/programs/{programme_id}/publish", json={"visibility": "public"}, headers=owner)
    assert again.json()["id"] == item.json()["id"] and again.json()["visibility"] == "public"
    assert client.get(f"/api/programs/{programme_id}/publication", headers=visitor).status_code == 404

    assert asyncio.run(api_module.generation_worker.run_once()) is True
    for _ in range(200):
        status = client.get(f"/api/programs/{programme_id}/publication", headers=owner).json()["status"]
        if status == "published":
            break
        time.sleep(0.05)
    assert status == "published"
    assert client.post(f"/api/published/{item.json()['id']}/copy", headers=visitor).status_code == 200
    # A programme that is not the caller's cannot be published at all.
    assert client.post(f"/api/programs/{programme_id}/publish", json={}, headers=visitor).status_code == 404


def test_a_publication_mixes_in_one_pass_whatever_the_owner_has_listened_to() -> None:
    """The owner's own position decided how far a step went, which made the first one nearly the whole mix."""
    from wavecast.models.episode import EpisodeState, LiveEpisode

    episode = LiveEpisode(
        seed_id="s", state=EpisodeState.MATERIALIZED, program_estimated_duration_seconds=1800,
        program_playback_position_seconds=800, segments=[],
    )
    assert api_module._render_ahead_seconds(episode, None, float("inf")) is None
    # Without a step it is still the listener's few minutes ahead of where they are.
    assert api_module._render_ahead_seconds(episode, None) == 800 + api_module.PROGRAMME_RENDER_AHEAD_SECONDS
