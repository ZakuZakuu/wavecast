import pytest
from wavecast.models.episode import CoverParams, EpisodeSeed, EpisodeState
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository
from wavecast.storage import EpisodeConcurrencyError


def test_stale_snapshot_cannot_overwrite_newer_in_memory_episode() -> None:
    repository = InMemoryEpisodeRepository()
    orchestrator = EpisodeOrchestrator(repository)
    seed = EpisodeSeed(
        id="cas-seed",
        title="CAS",
        topic="Test",
        short_description="Test",
        estimated_duration_seconds=1800,
        opening_track_ref="mock:opening",
        opening_track_title="Opening",
        opening_track_artist="Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )
    episode = orchestrator.start(seed)
    first = episode.model_copy(deep=True)
    stale = episode.model_copy(deep=True)

    first.state = EpisodeState.MATERIALIZED
    repository.save(first)

    stale.state = EpisodeState.STREAMING
    with pytest.raises(EpisodeConcurrencyError):
        repository.save(stale)

    reloaded = repository.get(episode.id)
    assert reloaded.state is EpisodeState.MATERIALIZED
    assert reloaded.version == first.version
