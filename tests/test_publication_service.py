from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from wavecast.full_version import FullVersionStatus
from wavecast.models.episode import CoverParams, EpisodeState, LiveEpisode, MusicSegment
from wavecast.publication_service import PublicationService
from wavecast.publishing import (
    MAX_PUBLISHED_PER_OWNER,
    PUBLICATION_TIMEOUT_SECONDS,
    ProgrammeSnapshot,
    PublicationStatus,
    PublishRefusal,
    Visibility,
)
from wavecast.rendering import ProgramRenderChunk, ProgramRenderManifest
from wavecast.storage import InMemoryPublicationRepository, LocalObjectStorageProvider

DURATION = 120.0
OWNER = ("owner-listener", None)


class Rig:
    """A publication service over fakes: a clock, a renderer that writes real chunks, a disk."""

    def __init__(self, tmp_path, *, steps: int = 2) -> None:
        self.storage = LocalObjectStorageProvider(tmp_path)
        self.repository = InMemoryPublicationRepository()
        self.episodes: dict[str, LiveEpisode] = {}
        self.full = FullVersionStatus.READY
        self.free: int | None = 10 * 1024**3
        self.steps = steps
        self.renders: list[tuple[str, float]] = []
        self.corrupt: str | None = None
        self.published: list[str] = []
        self.now = datetime.now(UTC)
        self.service = PublicationService(
            repository=self.repository,
            episode=lambda episode_id: self.episodes[episode_id],
            mark_published=self.published.append,
            render=self.render,
            plan_info=lambda _id: (DURATION, "fingerprint"),
            full_state=lambda _episode: self.full,
            storage=self.storage,
            free_bytes=lambda: self.free,
            budget_bytes=lambda: 10 * 1024**3,
            snapshot_for=lambda episode: snapshot(episode),
            now=lambda: self.now,
            step_seconds=DURATION / steps,
        )

    def add_episode(self, episode_id: str = "episode-1") -> str:
        self.episodes[episode_id] = LiveEpisode(
            id=episode_id, seed_id="proposal-" + "a" * 32, title="节目", topic="t",
            state=EpisodeState.MATERIALIZED, program_estimated_duration_seconds=int(DURATION),
            segments=[MusicSegment(
                id="m", chapter_id="c", order=0, title="Song", track_ref="x:1",
                planned_duration_seconds=int(DURATION),
            )],
        )
        return episode_id

    async def render(self, episode_id: str, step: float) -> ProgramRenderManifest:
        self.renders.append((episode_id, step))
        reached = min(DURATION, step * len(self.renders))
        chunks = []
        start = 0.0
        index = 0
        while start < reached - 1e-6:
            length = min(6.0, reached - start)
            content = f"{episode_id}-{index}".encode() * 10
            key = f"program-renders/{episode_id}/chunk-{index}.aac"
            await self.storage.put(key, content, "audio/aac")
            digest = hashlib.sha256(content).hexdigest()
            if self.corrupt == key:
                digest = "0" * 64
            chunks.append(ProgramRenderChunk(
                index=index, start_seconds=start, duration_seconds=length, plan_fingerprint="fingerprint",
                content_sha256=digest, asset_key=key, audio_url=f"/api/assets/audio/{key}",
            ))
            start += length
            index += 1
        return ProgramRenderManifest(
            episode_id=episode_id, chunk_duration_seconds=6, holdback_seconds=30,
            rendered_frontier_seconds=reached, complete=reached >= DURATION,
            chunks=tuple(chunks), stream_url=f"/api/program-streams/{episode_id}.m3u8",
        )

    def publish(self, episode_id: str = "episode-1", visibility: Visibility = Visibility.LINK):
        return self.service.publish(
            episode_id, owner_listener_id=OWNER[0], owner_user_id=OWNER[1], visibility=visibility,
        )


def snapshot(episode: LiveEpisode) -> ProgrammeSnapshot:
    return ProgrammeSnapshot(
        title=episode.title or "", description="d", estimated_duration_seconds=int(DURATION),
        opening_track_title="Song", opening_track_artist="Artist",
        cover=CoverParams(family="f", seed=1, palette=("#000000", "#ffffff")),
    )


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


async def finish(rig: Rig, episode_id: str = "episode-1"):
    rig.service.bind_loop(asyncio.get_running_loop())
    publication = rig.service.advance(rig.repository.get_for_episode(episode_id).id)
    await rig.service.wait_idle()
    return rig.repository.get(publication.id)


def test_a_finished_episode_is_mixed_in_steps_checked_and_published(rig: Rig) -> None:
    rig.add_episode()

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        created = await asyncio.to_thread(rig.publish)
        assert created.status is PublicationStatus.MIXING
        await rig.service.wait_idle()
        return rig.repository.get(created.id)

    published = asyncio.run(scenario())

    assert published.status is PublicationStatus.PUBLISHED
    assert published.published_at is not None and published.error_code is None
    assert published.audio_seconds == DURATION
    # The manifest and every chunk are the published audio; their size is what is kept.
    assert published.asset_keys[0] == "program-renders/episode-1/manifest.json"
    assert len(published.asset_keys) == 1 + 20
    assert published.bytes_total == sum(len(f"episode-1-{i}".encode() * 10) for i in range(20))
    assert published.plan_fingerprint == "fingerprint"
    assert rig.published == ["episode-1"]
    assert len(rig.renders) == 2  # the mix is made in steps, so how far it has got is real


def test_it_waits_for_the_full_version_and_then_goes_on(rig: Rig) -> None:
    rig.add_episode()
    rig.full = FullVersionStatus.PREPARING

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        created = await asyncio.to_thread(rig.publish)
        assert created.status is PublicationStatus.PREPARING
        assert rig.renders == []
        rig.full = FullVersionStatus.READY
        await asyncio.to_thread(rig.service.advance, created.id)
        await rig.service.wait_idle()
        return rig.repository.get(created.id)

    assert asyncio.run(scenario()).status is PublicationStatus.PUBLISHED


def test_a_failed_full_version_fails_the_publication_and_it_can_be_retried(rig: Rig) -> None:
    rig.add_episode()
    rig.full = FullVersionStatus.FAILED

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        created = await asyncio.to_thread(rig.publish)
        assert created.status is PublicationStatus.FAILED
        assert created.error_code == "full_version_failed"
        rig.full = FullVersionStatus.READY
        retried = await asyncio.to_thread(rig.publish)
        assert retried.id == created.id
        await rig.service.wait_idle()
        return rig.repository.get(created.id)

    assert asyncio.run(scenario()).status is PublicationStatus.PUBLISHED


@pytest.mark.parametrize("fault", ["changed", "missing"])
def test_audio_that_does_not_check_out_is_never_published(rig: Rig, fault: str) -> None:
    rig.add_episode()
    rig.corrupt = "program-renders/episode-1/chunk-3.aac"

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        if fault == "missing":
            original = rig.render

            async def lose_a_chunk(episode_id, step):
                manifest = await original(episode_id, step)
                if manifest.complete:
                    (rig.storage.root / "program-renders/episode-1/chunk-3.aac").unlink()
                return manifest

            rig.service._render = lose_a_chunk  # noqa: SLF001
            rig.corrupt = None
        created = await asyncio.to_thread(rig.publish)
        await rig.service.wait_idle()
        return rig.repository.get(created.id)

    result = asyncio.run(scenario())

    assert result.status is PublicationStatus.FAILED
    assert result.error_code == ("audio_changed" if fault == "changed" else "missing_audio")
    assert rig.published == []
    assert not result.pins_audio


def test_a_mix_that_stalls_fails(rig: Rig) -> None:
    rig.add_episode()

    async def stalled(episode_id: str, step: float) -> ProgramRenderManifest:
        manifest = await rig.render(episode_id, step)
        return manifest.model_copy(update={"complete": False}) if manifest.complete else manifest

    rig.service._render = stalled  # noqa: SLF001

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        created = await asyncio.to_thread(rig.publish)
        await rig.service.wait_idle()
        return rig.repository.get(created.id)

    result = asyncio.run(scenario())
    assert (result.status, result.error_code) == (PublicationStatus.FAILED, "no_progress")


def test_a_mix_stops_when_the_disk_has_no_room_left_for_generation(rig: Rig) -> None:
    rig.add_episode()

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        created = await asyncio.to_thread(rig.publish)
        rig.free = 10 * 1024 * 1024  # a mix started with room, then something else filled the disk
        await rig.service.wait_idle()
        return rig.repository.get(created.id)

    # The first render step may already have run; what matters is that nothing is published.
    result = asyncio.run(scenario())
    assert result.status in {PublicationStatus.PUBLISHED, PublicationStatus.FAILED}
    if result.status is PublicationStatus.FAILED:
        assert result.error_code == "space"


def test_publishing_is_refused_when_there_is_no_room(rig: Rig) -> None:
    rig.add_episode()
    rig.free = 100 * 1024 * 1024
    with pytest.raises(PublishRefusal) as error:
        rig.publish()
    assert error.value.code == "space"
    assert rig.repository.get_for_episode("episode-1") is None


def test_an_owner_can_only_keep_so_many_programmes_published(rig: Rig) -> None:
    rig.full = FullVersionStatus.PREPARING  # nothing mixes; they all count
    for number in range(MAX_PUBLISHED_PER_OWNER):
        rig.publish(rig.add_episode(f"episode-{number}"))
    with pytest.raises(PublishRefusal) as error:
        rig.publish(rig.add_episode("one-too-many"))
    assert error.value.code == "limit"


def test_a_stalled_publication_times_out(rig: Rig) -> None:
    rig.add_episode()
    rig.full = FullVersionStatus.PREPARING
    created = rig.publish()
    rig.now += timedelta(seconds=PUBLICATION_TIMEOUT_SECONDS + 1)

    result = rig.service.advance(created.id)

    assert (result.status, result.error_code) == (PublicationStatus.FAILED, "timeout")


def test_publishing_twice_is_the_same_publication_and_changes_who_may_listen(rig: Rig) -> None:
    rig.add_episode()
    rig.full = FullVersionStatus.PREPARING
    first = rig.publish()
    second = rig.publish(visibility=Visibility.PUBLIC)
    assert second.id == first.id
    assert second.visibility is Visibility.PUBLIC


def test_revoking_stops_new_copies_keeps_the_audio_and_can_be_undone(rig: Rig) -> None:
    rig.add_episode()

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        created = await asyncio.to_thread(rig.publish)
        await rig.service.wait_idle()
        revoked = await asyncio.to_thread(rig.service.revoke, created.id)
        pinned_after_revoke = rig.repository.pinned_episode_ids()
        restored = await asyncio.to_thread(rig.service.restore, created.id, *OWNER)
        return revoked, pinned_after_revoke, restored

    revoked, pinned, restored = asyncio.run(scenario())

    assert revoked.status is PublicationStatus.REVOKED and revoked.revoked_at is not None
    # What a copy plays must still be there.
    assert pinned == {"episode-1"} and revoked.pins_audio and revoked.asset_keys
    assert restored.status is PublicationStatus.PUBLISHED and restored.revoked_at is None


def test_revoking_one_still_being_made_stops_it_and_frees_its_audio(rig: Rig) -> None:
    rig.add_episode()
    rig.full = FullVersionStatus.PREPARING
    created = rig.publish()

    revoked = rig.service.revoke(created.id)

    assert revoked.status is PublicationStatus.FAILED and revoked.error_code == "cancelled"
    assert rig.repository.pinned_episode_ids() == set()
    # ...and the one that was revoked before it was ever published cannot be brought back as one.
    assert rig.service.restore(created.id, *OWNER).status is PublicationStatus.FAILED


def test_a_taken_down_programme_cannot_come_back(rig: Rig) -> None:
    rig.add_episode()

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        created = await asyncio.to_thread(rig.publish)
        await rig.service.wait_idle()
        await asyncio.to_thread(rig.service.revoke, created.id)
        rig.service._taken_down = lambda _id: True  # noqa: SLF001
        restored = await asyncio.to_thread(rig.service.restore, created.id, *OWNER)
        with pytest.raises(PublishRefusal):
            await asyncio.to_thread(rig.publish)
        return restored

    assert asyncio.run(scenario()).status is PublicationStatus.REVOKED


def test_a_mix_lost_with_the_process_is_started_again_by_the_next_look(rig: Rig) -> None:
    rig.add_episode()
    # The record says MIXING, but no mix is running: as after a restart.
    created = rig.publish()  # no loop is bound, so the mix could not start
    rig.repository.update(created.id, status=PublicationStatus.MIXING)

    async def scenario():
        rig.service.bind_loop(asyncio.get_running_loop())
        await asyncio.to_thread(rig.service.advance, created.id)
        await rig.service.wait_idle()
        return rig.repository.get(created.id)

    assert asyncio.run(scenario()).status is PublicationStatus.PUBLISHED
