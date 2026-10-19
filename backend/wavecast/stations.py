"""The five radio stations a listener can tune, as the backend sees them.

The web client owns the catalogue (names, frequencies, covers); the backend only needs the
station's identity and what it implies for hosting.  Stations differ in *how* they talk; the
shared floor (music first, no talk over lead vocals, grounded facts, a real ending) does not.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from wavecast.presentation import HostMode, PresentationIntent, infer_presentation_intent


class StationId(StrEnum):
    CASUAL = "casual"
    CRATE = "crate"
    PORTRAIT = "portrait"
    LINEAGE = "lineage"
    NIGHT = "night"


@dataclass(frozen=True)
class StationProfile:
    station_id: StationId
    name: str
    positioning: str
    host_mode: HostMode


STATION_PROFILES: dict[StationId, StationProfile] = {
    StationId.CASUAL: StationProfile(
        StationId.CASUAL, "随便听", "随时开着的电台：音乐为主，主持人偶尔说两句，做什么事时听都行", HostMode.LIGHT
    ),
    StationId.CRATE: StationProfile(
        StationId.CRATE, "唱片行", "同好带你挖歌：从一首喜欢的歌出发，往外挖没听过的", HostMode.LIGHT
    ),
    StationId.PORTRAIT: StationProfile(
        StationId.PORTRAIT, "人物志", "一位歌手的路：用作品讲他走过的路", HostMode.FULL
    ),
    StationId.LINEAGE: StationProfile(
        StationId.LINEAGE, "来龙去脉", "一种风格的来历：跨年代串起来听", HostMode.FULL
    ),
    StationId.NIGHT: StationProfile(
        StationId.NIGHT, "夜里", "纯听歌，不说话，节奏放缓", HostMode.NONE
    ),
}


# The station identity and fallback when the proposal has no usable episode-specific lead.
# One flowing sentence or two: what we begin with
# (and, only when the listener's request names the artist, that it is theirs), then the station
# by name and frequency.  The frequency is read digit by digit, like a year, without the decimal
# point ("FM九七四"), which is how radio announces it; digits themselves are avoided because the
# voice reads them unpredictably.
STATION_TAGS: dict[StationId, str] = {
    StationId.CASUAL: "欢迎收听FM八八七，随便听",
    StationId.CRATE: "欢迎来到唱片行，FM九三一",
    StationId.PORTRAIT: "欢迎收听FM九七四，人物志",
    StationId.LINEAGE: "欢迎收听FM一零一五，来龙去脉",
}

_OPENING_PLAIN = (
    "现在先来听{artist}的《{title}》。{tag}。",
    "{tag}。先来听{artist}的《{title}》。",
    "{tag}，先来一首{artist}的《{title}》。",
)
_OPENING_NAMED = (
    "现在先来听《{title}》，来自你点的{artist}。{tag}。",
    "{tag}。你点了{artist}，那就先来听《{title}》。",
    "先来听《{title}》，是你点的{artist}。{tag}。",
)
# No station name to give (夜里, or a request with no station): just what begins.
_OPENING_BARE_PLAIN = ("先来听{artist}的《{title}》。", "第一首，{artist}的《{title}》。")
_OPENING_BARE_NAMED = ("先来听《{title}》，是你点的{artist}。", "你点了{artist}，先来听《{title}》。")


# How a programme ends.  The Writer says what the route was about; this closes it, in code, with
# the station's name and frequency and a plain goodbye, so every ending lands the same way.
_SIGNOFFS: dict[StationId, tuple[str, ...]] = {
    StationId.CASUAL: (
        "这里是FM八八七，随便听，我们下次再见。",
        "FM八八七，随便听，回头接着放。",
        "随便听，FM八八七，下次再见。",
    ),
    StationId.CRATE: (
        "这里是FM九三一，唱片行，下次再挖。",
        "FM九三一，唱片行，我们下次再见。",
        "唱片行，FM九三一，回头接着挖。",
    ),
    StationId.PORTRAIT: (
        "这里是FM九七四，人物志，我们下次再见。",
        "FM九七四，人物志，下次再会。",
        "人物志，FM九七四，下次再见。",
    ),
    StationId.LINEAGE: (
        "这里是FM一零一五，来龙去脉，我们下次再见。",
        "FM一零一五，来龙去脉，下次接着往下讲。",
        "来龙去脉，FM一零一五，下次再见。",
    ),
}


def compose_signoff(station: StationId | None, seed: str) -> str | None:
    """The station's closing line, or None (夜里 and a programme with no station say none)."""

    forms = _SIGNOFFS.get(station) if station is not None else None
    if not forms:
        return None
    digest = hashlib.sha256(f"signoff|{station}|{seed}".encode()).digest()
    return forms[int.from_bytes(digest[:4], "big") % len(forms)]


def compose_opening(
    station: StationId | None,
    *,
    artist: str,
    title: str,
    names_artist: bool,
    seed: str,
) -> str:
    """The spoken opening for a Chinese programme; the station's name is said when it has one."""

    tag = STATION_TAGS.get(station) if station is not None else None
    forms: tuple[str, ...]
    if tag is None:
        forms = _OPENING_BARE_NAMED if names_artist else _OPENING_BARE_PLAIN
    else:
        forms = _OPENING_NAMED if names_artist else _OPENING_PLAIN
    digest = hashlib.sha256(f"opening|{station}|{seed}".encode()).digest()
    form = forms[int.from_bytes(digest[:4], "big") % len(forms)]
    return form.format(artist=artist, title=title, tag=tag or "")


def resolve_presentation_intent(
    prompt: str, station: StationId | None, host_mode: HostMode | None = None
) -> PresentationIntent:
    """Presentation policy for a request.

    Order of precedence: the host control, when the listener touched it; explicit wording in the
    request ("只听歌", "多讲一点"); the station's default.
    """

    inferred = infer_presentation_intent(prompt)
    if host_mode is not None:
        return inferred.model_copy(update={"host_mode": host_mode})
    if station is None:
        return inferred
    profile = STATION_PROFILES[station]
    if inferred.host_mode is not PresentationIntent().host_mode:
        return inferred
    return inferred.model_copy(update={"host_mode": profile.host_mode})
