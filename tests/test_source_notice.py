"""A requested artist the route cannot play is reported to the client as data."""

from wavecast.models.progressive import ProgressiveAssemblySession

from services.api import main as api_module
from services.api.main import SEEDS


def _episode():
    return api_module.orchestrator.start(SEEDS[0], listener_id="source-notice-listener")


def test_no_notice_when_every_requested_artist_plays() -> None:
    episode = _episode()
    episode.progressive_session = ProgressiveAssemblySession.model_construct(unfulfilled_artists=[])

    assert episode.model_dump(mode="json")["source_notice"] is None


def test_no_notice_without_a_progressive_session() -> None:
    assert _episode().model_dump(mode="json")["source_notice"] is None


def test_unplayable_requested_artists_are_named_in_the_notice() -> None:
    episode = _episode()
    episode.progressive_session = ProgressiveAssemblySession.model_construct(
        unfulfilled_artists=["椎名林檎"]
    )

    assert episode.model_dump(mode="json")["source_notice"] == {
        "kind": "UNPLAYABLE_ARTISTS",
        "artists": ["椎名林檎"],
    }


def test_the_session_itself_still_stays_out_of_the_api_payload() -> None:
    episode = _episode()
    episode.progressive_session = ProgressiveAssemblySession.model_construct(
        unfulfilled_artists=["椎名林檎"]
    )

    assert "progressive_session" not in episode.model_dump(mode="json")
