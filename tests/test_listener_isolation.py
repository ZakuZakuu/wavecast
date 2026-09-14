from wavecast.models.episode import CoverParams, EpisodeSeed
from wavecast.orchestration.episode import EpisodeOrchestrator, InMemoryEpisodeRepository


def seed() -> EpisodeSeed:
    return EpisodeSeed(
        id="shared-seed",
        title="Shared",
        topic="Test",
        short_description="Test",
        estimated_duration_seconds=1800,
        opening_track_ref="mock:opening",
        opening_track_title="Opening",
        opening_track_artist="Artist",
        cover=CoverParams(family="editorial", seed=1, palette=("#000", "#fff")),
    )


def test_listener_identity_scopes_resume_and_prevents_cross_listener_reuse() -> None:
    orchestrator = EpisodeOrchestrator(InMemoryEpisodeRepository())
    first_a = orchestrator.start_or_resume(seed(), "listener-a")
    resumed_a = orchestrator.start_or_resume(seed(), "listener-a")
    first_b = orchestrator.start_or_resume(seed(), "listener-b")

    assert resumed_a.id == first_a.id
    assert first_b.id != first_a.id
    assert first_b.listener_id == "listener-b"
