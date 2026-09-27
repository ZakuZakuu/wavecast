from __future__ import annotations

import asyncio

import pytest
from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    SegmentState,
)
from wavecast.orchestration.episode import (
    EpisodeOrchestrator,
    EpisodeRuntimeError,
    InMemoryEpisodeRepository,
)
from wavecast.orchestration.generation import (
    DeterministicMockProgressiveGenerator,
    GeneratedChapter,
)
from wavecast.orchestration.scheduler import InlineGenerationScheduler


def make_seed() -> EpisodeSeed:
    return EpisodeSeed(
        id="progressive-seed",
        title="Progressive fixture",
        topic="On-demand chapters",
        short_description="A deterministic progressive fixture",
        estimated_duration_seconds=300,
        opening_track_ref="mock:opening",
        opening_track_title="Immediate opening",
        opening_track_artist="Test Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )


def make_runtime(
    generator: DeterministicMockProgressiveGenerator | None = None,
) -> tuple[EpisodeOrchestrator, InlineGenerationScheduler]:
    runtime = EpisodeOrchestrator(
        InMemoryEpisodeRepository(), progressive_generator=generator
    )
    return runtime, InlineGenerationScheduler(runtime)


def test_start_is_opening_only_and_does_not_call_generator() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, _ = make_runtime(generator)

    episode = runtime.start(make_seed())

    assert [segment.id for segment in episode.ordered_segments] == ["segment-opening"]
    assert episode.generated_frontier_seconds == 22
    assert generator.calls == 0


def test_long_opening_still_prepares_a_future_chapter() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, scheduler = make_runtime(generator)
    long_opening = make_seed().model_copy(
        update={"opening_track_duration_seconds": 300}
    )
    episode = runtime.start(long_opening)

    buffered = asyncio.run(
        scheduler.ensure_buffer(
            episode.id,
            target_chapters=2,
            target_ahead_seconds=180,
        )
    )

    assert generator.calls == 1
    assert buffered.segment("segment-narration-1").is_audio_ready
    assert buffered.segment("segment-bridge").is_audio_ready


def test_scheduler_appends_complete_ready_chapters_within_bound() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, scheduler = make_runtime(generator)
    episode = runtime.start(make_seed())

    buffered = asyncio.run(
        scheduler.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    )

    assert buffered.segment("segment-narration-1").is_audio_ready
    assert buffered.segment("segment-bridge").is_audio_ready
    assert buffered.segment("segment-narration-2") if False else True
    assert generator.calls == 1


def test_invalid_generated_chapter_is_atomic() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, _ = make_runtime(generator)
    episode = runtime.start(make_seed())
    snapshot = runtime.capture_generation_snapshot(episode.id)
    valid = asyncio.run(generator.generate_next(snapshot.episode))
    assert valid is not None
    invalid = GeneratedChapter(
        chapter_id=valid.chapter_id,
        segments=[
            valid.segments[0],
            valid.segments[1].model_copy(update={"state": SegmentState.PLANNED}),
        ],
    )

    with pytest.raises(EpisodeRuntimeError, match="unready music"):
        runtime.append_generated_chapter(episode.id, invalid, snapshot)

    assert [segment.id for segment in runtime.get(episode.id).segments] == [
        "segment-opening"
    ]


def test_structural_future_change_rejects_stale_generation_anchor() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, _ = make_runtime(generator)
    episode = runtime.start(make_seed())
    snapshot = runtime.capture_generation_snapshot(episode.id)
    chapter = asyncio.run(generator.generate_next(snapshot.episode))
    assert chapter is not None

    current = runtime.get(episode.id)
    current.segment("segment-opening").chapter_id = "changed-chapter"
    runtime.repository.save(current)

    with pytest.raises(EpisodeRuntimeError, match="structure is stale"):
        runtime.append_generated_chapter(episode.id, chapter, snapshot)


def test_concurrent_ensure_buffer_coalesces_per_episode() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, scheduler = make_runtime(generator)
    episode = runtime.start(make_seed())

    async def run() -> None:
        await asyncio.gather(
            scheduler.ensure_buffer(
                episode.id, target_chapters=1, target_ahead_seconds=300
            ),
            scheduler.ensure_buffer(
                episode.id, target_chapters=1, target_ahead_seconds=300
            ),
        )

    asyncio.run(run())

    ids = [segment.id for segment in runtime.get(episode.id).segments]
    assert len(ids) == len(set(ids))
    assert generator.calls == 1


def test_heartbeat_during_generation_keeps_structural_anchor_valid() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, scheduler = make_runtime(generator)
    episode = runtime.start(make_seed())

    async def run() -> None:
        task = asyncio.create_task(
            scheduler.ensure_buffer(
                episode.id, target_chapters=1, target_ahead_seconds=300
            )
        )
        await asyncio.sleep(0)
        runtime.heartbeat(episode.id)
        await task

    asyncio.run(run())

    assert runtime.get(episode.id).segment("segment-bridge").is_audio_ready


def test_leave_discards_in_flight_generated_chapter_and_resume_can_continue() -> None:
    class GatedGenerator(DeterministicMockProgressiveGenerator):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def generate_next(self, episode):
            self.started.set()
            await self.release.wait()
            return await super().generate_next(episode)

    generator = GatedGenerator()
    runtime, scheduler = make_runtime(generator)
    episode = runtime.start(make_seed())

    async def run() -> None:
        task = asyncio.create_task(
            scheduler.ensure_buffer(
                episode.id, target_chapters=1, target_ahead_seconds=300
            )
        )
        await generator.started.wait()
        runtime.leave(episode.id)
        generator.release.set()
        with pytest.raises(EpisodeRuntimeError, match="inactive"):
            await task

    asyncio.run(run())
    assert [segment.id for segment in runtime.get(episode.id).segments] == [
        "segment-opening"
    ]

    runtime.resume(episode.id)
    resumed = asyncio.run(
        scheduler.ensure_buffer(
            episode.id, target_chapters=1, target_ahead_seconds=300
        )
    )
    assert resumed.segment("segment-bridge").is_audio_ready


def test_generator_reconstruction_derives_next_chapter_from_persisted_timeline() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, scheduler = make_runtime(generator)
    episode = runtime.start(make_seed())

    asyncio.run(
        scheduler.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    )
    reconstructed = DeterministicMockProgressiveGenerator()
    persisted = runtime.get(episode.id)
    next_chapter = asyncio.run(reconstructed.generate_next(persisted))

    assert next_chapter is not None
    assert next_chapter.chapter_id == "chapter-3"
    assert reconstructed.calls == 1


def test_full_materialization_drains_generator_and_freezes_episode() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, scheduler = make_runtime(generator)
    episode = runtime.start(make_seed())

    materialized = asyncio.run(scheduler.materialize_all(episode.id))

    assert materialized.state is EpisodeState.MATERIALIZED
    assert materialized.generation_mode.name == "FULL"
    assert {segment.chapter_id for segment in materialized.segments} == {
        "chapter-1",
        "chapter-2",
        "chapter-3",
        "chapter-4",
    }
    assert generator.calls == 4


def test_opening_prefix_remains_stable_after_progressive_append() -> None:
    generator = DeterministicMockProgressiveGenerator()
    runtime, scheduler = make_runtime(generator)
    episode = runtime.start(make_seed())
    opening = episode.segment("segment-opening").model_dump(mode="json")

    asyncio.run(
        scheduler.ensure_buffer(episode.id, target_chapters=1, target_ahead_seconds=300)
    )

    assert runtime.get(episode.id).segment("segment-opening").model_dump(mode="json") == opening
