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
        StationId.CASUAL, "随便听", "开车时开着的电台：音乐为主，主持人偶尔说两句", HostMode.LIGHT
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


# Station identifications, spoken once near the start of a programme, after the first piece of
# content.  They are written by us, not by the Writer, so they stay short and never turn into
# a new stock phrase: a few forms per station, one picked from the programme's seed.  Numbers
# are spelled out because the voice reads digits unpredictably.
STATION_IDENTS: dict[StationId, tuple[str, ...]] = {
    StationId.CASUAL: (
        "这里是随便听，八十八点七。",
        "随便听，调频八十八点七。",
        "你听的是随便听。",
    ),
    StationId.CRATE: (
        "这里是唱片行，九十三点一。",
        "唱片行，调频九十三点一。",
        "你听的是唱片行。",
    ),
    StationId.PORTRAIT: (
        "这里是人物志，九十七点四。",
        "人物志，调频九十七点四。",
        "你听的是人物志。",
    ),
    StationId.LINEAGE: (
        "这里是来龙去脉，一百零一点五。",
        "来龙去脉，调频一百零一点五。",
        "你听的是来龙去脉。",
    ),
}


def pick_ident(station: StationId | None, seed: str) -> str | None:
    """The station identification for a programme, or ``None`` (夜里 and unknown stations)."""

    if station is None or station not in STATION_IDENTS:
        return None
    forms = STATION_IDENTS[station]
    digest = hashlib.sha256(f"ident|{station.value}|{seed}".encode()).digest()
    return forms[int.from_bytes(digest[:4], "big") % len(forms)]


def resolve_presentation_intent(prompt: str, station: StationId | None) -> PresentationIntent:
    """Presentation policy for a request: the station's default, unless the listener asked.

    Explicit wording in the request ("只听歌", "多讲一点") always wins over the station.
    """

    inferred = infer_presentation_intent(prompt)
    if station is None:
        return inferred
    profile = STATION_PROFILES[station]
    if inferred.host_mode is not PresentationIntent().host_mode:
        return inferred
    return inferred.model_copy(update={"host_mode": profile.host_mode})
