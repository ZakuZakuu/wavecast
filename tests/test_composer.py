import asyncio

import pytest
from wavecast.composer import EpisodeComposer
from wavecast.intelligence.models import (
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.intelligence.resolution import UnresolvedTrackError
from wavecast.providers.fakes import MockMusicProvider


def test_composer_creates_a_playable_radio_timeline() -> None:
    tracks = [
        ResolvedTrack(
            track_ref="mock:opening",
            canonical_artist="Mira Fields",
            canonical_title="Neon First Light",
        ),
        ResolvedTrack(
            track_ref="mock:bridge",
            canonical_artist="Signal Garden",
            canonical_title="Midnight Transfer",
        ),
    ]
    script = RadioScript(
        blocks=[
            RadioScriptBlock(kind=RadioScriptBlockKind.INTRO, text="Welcome to the night.", duration_seconds=8),
            RadioScriptBlock(kind=RadioScriptBlockKind.TRANSITION, text="Now we widen the frame.", duration_seconds=7),
        ],
        intended_duration_seconds=90,
    )

    episode = asyncio.run(EpisodeComposer(MockMusicProvider()).compose(tracks, script))

    assert [segment.kind.value for segment in episode.segments] == [
        "MUSIC",
        "NARRATION",
        "MUSIC",
        "NARRATION",
    ]
    assert episode.segments[0].audio_source_url is not None
    assert episode.segments[0].state.value == "AUDIO_READY"
    assert episode.segments[1].narration_text == "Welcome to the night."
    assert episode.segments[-1].narration_text == "Now we widen the frame."
    assert episode.duration_seconds == 61


def test_composer_rejects_unresolved_proposals_before_playback() -> None:
    proposal = TrackProposal(artist="Unknown", title="Uncatalogued", confidence=0.2)

    with pytest.raises(UnresolvedTrackError):
        asyncio.run(EpisodeComposer(MockMusicProvider()).compose([proposal], RadioScript(blocks=[])))
