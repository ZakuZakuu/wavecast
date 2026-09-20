import pytest
from wavecast.models.episode import (
    EpisodeState,
    MusicSegment,
    NarrationSegment,
    PlayableEpisode,
    SegmentState,
)
from wavecast.orchestration.episode import (
    EpisodeOrchestrator,
    EpisodeRuntimeError,
    InMemoryEpisodeRepository,
)


def playable_episode() -> PlayableEpisode:
    return PlayableEpisode(
        id="assembled-episode",
        segments=[
            MusicSegment(
                id="track-1",
                chapter_id="chapter-1",
                order=0,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=12,
                actual_duration_seconds=12,
                track_ref="audius:track-1",
                audio_source_url="/api/audio/audius/track-1",
                title="Opening track",
                artist="Artist One",
            ),
            NarrationSegment(
                id="narration-1",
                chapter_id="chapter-1",
                order=1,
                state=SegmentState.AUDIO_READY,
                planned_duration_seconds=5,
                actual_duration_seconds=5,
                audio_source_url="/api/assets/audio/narration-1.wav",
                title="A musical connection",
                narration_text="A short editorial bridge.",
            ),
        ],
    )


def test_import_materialized_episode_reuses_existing_runtime_and_is_fully_seekable() -> None:
    runtime = EpisodeOrchestrator(InMemoryEpisodeRepository())

    episode = runtime.import_materialized(
        seed_id="fang-datong-soul-rnb",
        title="从方大同出发",
        topic="Soul / R&B 音乐语言",
        estimated_duration_seconds=17,
        playable_episode=playable_episode(),
    )

    assert episode.state is EpisodeState.MATERIALIZED
    assert episode.generation_mode.value == "FULL"
    assert episode.title == "从方大同出发"
    assert episode.generated_frontier_seconds == 17
    assert episode.segment("track-1").state is SegmentState.COMMITTED
    assert episode.segment("narration-1").state is SegmentState.AUDIO_READY

    seeked = runtime.seek(episode.id, 16)
    assert seeked.playback_position_seconds == 16

    resumed = runtime.import_materialized(
        seed_id="fang-datong-soul-rnb",
        title="从方大同出发",
        topic="Soul / R&B 音乐语言",
        estimated_duration_seconds=17,
        playable_episode=playable_episode(),
    )
    assert resumed.id == episode.id


def test_import_materialized_episode_rejects_missing_browser_audio() -> None:
    runtime = EpisodeOrchestrator(InMemoryEpisodeRepository())
    base = playable_episode()
    invalid = base.model_copy(
        update={"segments": [base.segments[0].model_copy(update={"audio_source_url": None})]}
    )

    with pytest.raises(EpisodeRuntimeError, match="without audio"):
        runtime.import_materialized(
            seed_id="invalid",
            title="Invalid",
            topic="Invalid",
            estimated_duration_seconds=12,
            playable_episode=invalid,
        )


def test_import_materialized_episode_rejects_external_audio_url() -> None:
    runtime = EpisodeOrchestrator(InMemoryEpisodeRepository())
    base = playable_episode()
    invalid = base.model_copy(
        update={
            "segments": [
                base.segments[0].model_copy(
                    update={"audio_source_url": "https://cdn.example.test/temporary.mp3"}
                ),
                base.segments[1],
            ]
        }
    )

    with pytest.raises(EpisodeRuntimeError, match="external audio URL"):
        runtime.import_materialized(
            seed_id="invalid-external-url",
            title="Invalid",
            topic="Invalid",
            estimated_duration_seconds=17,
            playable_episode=invalid,
        )
