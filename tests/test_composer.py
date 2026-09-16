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
        "NARRATION",
        "MUSIC",
    ]
    assert episode.segments[0].audio_source_url is not None
    assert episode.segments[0].state.value == "AUDIO_READY"
    assert episode.segments[1].narration_text == "Welcome to the night."
    assert episode.segments[2].narration_text == "Now we widen the frame."
    assert episode.segments[3].track_ref == "mock:bridge"
    assert episode.duration_seconds == 61


def test_composer_assigns_multiple_intros_and_transitions_to_their_gaps() -> None:
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
        ResolvedTrack(
            track_ref="mock:resolution",
            canonical_artist="Southbound FM",
            canonical_title="Daybreak in Stereo",
        ),
    ]
    script = RadioScript(
        blocks=[
            RadioScriptBlock(
                kind=RadioScriptBlockKind.TRACK_INTRO,
                text="Opening track context.",
                duration_seconds=4,
                track_index=0,
            ),
            RadioScriptBlock(
                kind=RadioScriptBlockKind.INTRO,
                text="After the opening track.",
                duration_seconds=4,
            ),
            RadioScriptBlock(
                kind=RadioScriptBlockKind.TRANSITION,
                text="First gap.",
                duration_seconds=4,
                track_index=0,
            ),
            RadioScriptBlock(
                kind=RadioScriptBlockKind.TRACK_INTRO,
                text="Bridge track context.",
                duration_seconds=4,
                track_index=1,
            ),
            RadioScriptBlock(
                kind=RadioScriptBlockKind.TRANSITION,
                text="Second gap fallback.",
                duration_seconds=4,
            ),
            RadioScriptBlock(
                kind=RadioScriptBlockKind.TRACK_INTRO,
                text="Resolution track context.",
                duration_seconds=4,
                track_index=2,
            ),
        ]
    )

    episode = asyncio.run(EpisodeComposer(MockMusicProvider()).compose(tracks, script))

    assert [segment.kind.value for segment in episode.segments] == [
        "NARRATION",
        "MUSIC",
        "NARRATION",
        "NARRATION",
        "NARRATION",
        "MUSIC",
        "NARRATION",
        "NARRATION",
        "MUSIC",
    ]
    assert [segment.narration_text for segment in episode.segments if segment.narration_text] == [
        "Opening track context.",
        "After the opening track.",
        "First gap.",
        "Bridge track context.",
        "Second gap fallback.",
        "Resolution track context.",
    ]
    assert episode.segments[2].narration_text == "After the opening track."
    assert episode.segments[3].narration_text == "First gap."
    assert episode.segments[4].narration_text == "Bridge track context."
    assert episode.segments[6].narration_text == "Second gap fallback."


def test_composer_rejects_unresolved_proposals_before_playback() -> None:
    proposal = TrackProposal(artist="Unknown", title="Uncatalogued", confidence=0.2)

    with pytest.raises(UnresolvedTrackError):
        asyncio.run(EpisodeComposer(MockMusicProvider()).compose([proposal], RadioScript(blocks=[])))


def test_composer_preserves_provider_neutral_tts_cues() -> None:
    episode = asyncio.run(
        EpisodeComposer(MockMusicProvider()).compose(
            [
                ResolvedTrack(
                    track_ref="mock:opening",
                    canonical_artist="Mira Fields",
                    canonical_title="Neon First Light",
                )
            ],
            RadioScript(
                blocks=[
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.INTRO,
                        text="Welcome to the night.",
                        duration_seconds=8,
                        tts_cues=["pause_short", "breath"],
                    )
                ]
            ),
        )
    )

    narration = next(segment for segment in episode.segments if segment.narration_text)
    assert narration.tts_cues == ["pause_short", "breath"]


def test_composer_keeps_narration_only_blocks_without_music_substitution() -> None:
    tracks = [
        ResolvedTrack(
            track_ref="mock:opening",
            canonical_artist="Mira Fields",
            canonical_title="Neon First Light",
        ),
        None,
        ResolvedTrack(
            track_ref="mock:bridge",
            canonical_artist="Signal Garden",
            canonical_title="Midnight Transfer",
        ),
    ]
    episode = asyncio.run(
        EpisodeComposer(MockMusicProvider()).compose(
            tracks,
            RadioScript(
                blocks=[
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.TRANSITION,
                        text="This is a story beat without a track.",
                        duration_seconds=4,
                    )
                ]
            ),
        )
    )

    assert [segment.track_ref for segment in episode.segments if segment.kind.value == "MUSIC"] == [
        "mock:opening",
        "mock:bridge",
    ]
    assert any(
        segment.narration_text == "This is a story beat without a track."
        for segment in episode.segments
    )


def test_composer_can_render_a_narration_only_episode() -> None:
    episode = asyncio.run(
        EpisodeComposer(MockMusicProvider()).compose(
            [None],
            RadioScript(
                blocks=[
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.TRANSITION,
                        text="Context before any song.",
                        duration_seconds=4,
                    )
                ]
            ),
        )
    )

    assert len(episode.segments) == 1
    assert episode.segments[0].narration_text == "Context before any song."


def test_composer_keeps_multiple_narration_beats_in_one_music_gap() -> None:
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
    episode = asyncio.run(
        EpisodeComposer(MockMusicProvider()).compose(
            tracks,
            RadioScript(
                blocks=[
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.TRANSITION,
                        text="Narration A",
                        duration_seconds=3,
                    ),
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.TRANSITION,
                        text="Narration B",
                        duration_seconds=3,
                    ),
                ]
            ),
        )
    )

    assert [
        (segment.kind.value, segment.narration_text or segment.track_ref)
        for segment in episode.segments
    ] == [
        ("MUSIC", "mock:opening"),
        ("NARRATION", "Narration A"),
        ("NARRATION", "Narration B"),
        ("MUSIC", "mock:bridge"),
    ]


def test_composer_preserves_visible_and_tts_text() -> None:
    episode = asyncio.run(
        EpisodeComposer(MockMusicProvider()).compose(
            [
                ResolvedTrack(
                    track_ref="mock:opening",
                    canonical_artist="Mira Fields",
                    canonical_title="Neon First Light",
                )
            ],
            RadioScript(
                blocks=[
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.INTRO,
                        text="3rd Coast",
                        tts_text="Third Coast",
                        duration_seconds=4,
                    )
                ]
            ),
        )
    )

    narration = next(segment for segment in episode.segments if segment.narration_text)
    assert narration.narration_text == "3rd Coast"
    assert narration.tts_text == "Third Coast"
