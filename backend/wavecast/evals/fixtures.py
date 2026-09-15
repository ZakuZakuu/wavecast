"""Credential-free Guided Discovery benchmark inputs.

Cases intentionally describe failure modes rather than prescribing exact tracks.  Evaluation
should reward musical reasoning, evidence discipline, and a coherent arc instead of memorization.
"""

from .quality import GuidedDiscoveryCase

GUIDED_DISCOVERY_CASES: tuple[GuidedDiscoveryCase, ...] = (
    GuidedDiscoveryCase(
        case_id="third-coast-same-artist-trap",
        title="3rd Coast beyond the immediate cluster",
        topic="guided discovery around smooth urban lounge music",
        anchor_tracks=["3rd Coast - Jealousy", "3rd Coast - Luv is True"],
        failure_mode="same-artist and game-franchise repetition",
        expected_dimensions=["groove", "harmony", "production texture", "vocal interplay"],
    ),
    GuidedDiscoveryCase(
        case_id="persona-style-explanation",
        title="Game-music style without an OST-only list",
        topic="Persona P3/P4/P5 inspired guided discovery",
        anchor_tracks=["Persona 4 - Reach Out To The Truth"],
        failure_mode="confusing soundtrack context with musical traits",
        expected_dimensions=["jazz harmony", "funk rhythm", "club production", "instrumentation"],
    ),
    GuidedDiscoveryCase(
        case_id="artist-to-scene-bridge",
        title="Artist to scene and era",
        topic="guided discovery from trip-hop into adjacent late-1990s production language",
        anchor_tracks=["Portishead - Glory Box"],
        failure_mode="shallow same-artist similarity",
        expected_dimensions=["harmonic language", "sampling", "vocal treatment", "era"],
    ),
    GuidedDiscoveryCase(
        case_id="late-night-city-drive",
        title="Relaxed but rhythmic night drive",
        topic="relaxed late-night city driving, rhythmic but not aggressive",
        anchor_artists=["Sade"],
        failure_mode="incoherent mood-playlist dumping",
        expected_dimensions=["tempo feel", "bass texture", "vocal intimacy", "emotional energy"],
    ),
)
