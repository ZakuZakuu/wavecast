"""Shared editorial method and the first inter-track passage's writing task.

These are directions, not a script template or an additional agent stage.
"""

from wavecast.presentation import HostMode
from wavecast.stations import STATION_PROFILES, StationId

EDITORIAL_METHOD = (
    "Start from what the listener wants to discover or feel, and find a specific question, "
    "observation or listening direction worth following. Let research refine that direction; "
    "do not decide a conclusion and force songs to prove it. Songs can offer examples, "
    "contrast, discovery or breathing room. Give each spoken passage a useful job so the "
    "programme develops rather than listing tracks. A song's narrator is not the artist: "
    "do not turn lyrics into the artist's biography or intentions. The opening sets an "
    "expectation the actual programme can fulfil; do not promise unconfirmed songs or facts. "
)

_STATION_APPROACH = {
    StationId.PORTRAIT: "Explore a person through their work and the requested angle; a career chronology is optional.",
    StationId.LINEAGE: "Follow a musical idea through connections and contrasts; a chronological history is optional.",
    StationId.CRATE: "Help a fellow listener discover why these selections belong together and where to listen next.",
    StationId.CASUAL: "Offer easy musical company and a small, specific reason to keep listening; no compulsory thesis.",
    StationId.NIGHT: "Let the musical sequence carry the mood; hosting is normally absent.",
}


def editorial_station_guidance(station: StationId | None) -> str:
    if station is None:
        return ""
    return (
        f"Station: {STATION_PROFILES[station].name}. {_STATION_APPROACH[station]} "
        "This is a default approach, not a required structure; the listener's explicit request wins.\n"
    )


def closing_passage_guidance() -> str:
    return (
        "This is the programme's substantive closing, not a track introduction. "
        "Return to the opening's listening question or direction, using only the actual route "
        "and earlier host passages below. Explain what those examples add to our understanding; "
        "leave room for a nuanced or open answer. Do not just list songs or repeat the opening. "
        "Introduce no new biography, research or factual claim, and promise nothing to come. "
        "The route and earlier script describe what aired; they are not independent factual evidence. "
        "Give the final outro the main space, aiming at 30–45 seconds including the sign-off; "
        "any before-track handoff in the same request is optional and brief. "
        "Use your own natural structure, without a required sentence count or padding. "
        "Do not add a farewell or station name: the application appends the sign-off.\n"
    )


def opening_passage_guidance(station: StationId | None, host_mode: HostMode) -> str:
    density = (
        "Develop a concrete direction the listener can follow through this programme, "
        "rather than just announcing the next song. "
        if host_mode is HostMode.FULL
        else "Keep the connection brief and useful; mood or a selection idea is enough. "
        "Do not impose an essay or a long explanation on light hosting. "
    )
    return (
        EDITORIAL_METHOD
        + "\n"
        + editorial_station_guidance(station)
        + "This is the substantive opening passage at the supplied playback position, normally "
        "after the first song and before the second. If an earlier opening was skipped, "
        "establish the direction from the current pair instead of pretending this is the first gap. "
        "Use the confirmed pair and the editorial intention to establish what is worth "
        "following, and give the next song a natural place in that direction. "
        + density
        + "The earlier short opening, if present, has already welcomed the listener: "
        "advance its idea without repeating a greeting, station ID or the same pitch. "
        "The passage should also make sense if that short opening was absent or skipped. "
        "The proposal description is an intention, not evidence, an established conclusion "
        "or a confirmed playlist. Without evidence, frame an exploration rather than "
        "inventing sonic details, lyric meanings, biography or connections between songs. "
        "If the pair does not support the proposed angle, narrow the direction honestly. "
        "Use natural spoken language and your own structure; no mandatory question, "
        "three-part outline, rhetorical pattern or minimum length. Stop when the idea is clear.\n"
    )
