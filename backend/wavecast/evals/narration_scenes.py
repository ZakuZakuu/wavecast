"""Fixed Writer scenes for comparing narration prompts before and after a change.

Each scene is one narration slot with its adjacent tracks and a few illustrative evidence
lines.  The facts are only fixtures for measuring *how* the Writer talks; they are not
published content and are not claimed to be verified here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from wavecast.intelligence.models import (
    ChapterPlan,
    Evidence,
    NarrationSlotContext,
    NarrationSlotPlacement,
    NarrativeRole,
    NoveltyDistance,
    RadioScriptBlockKind,
    ResolvedTrack,
)
from wavecast.stations import StationId


@dataclass(frozen=True)
class NarrationScene:
    scene_id: str
    topic: str
    kind: RadioScriptBlockKind
    just_played: ResolvedTrack | None
    upcoming: ResolvedTrack | None
    facts: tuple[str, ...] = ()
    window_seconds: int = 14
    is_opening: bool = False
    is_final: bool = False
    reason: str = "continue the programme's route"
    previous_context: str = ""
    station: StationId | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def chapter(self) -> ChapterPlan:
        return ChapterPlan(
            index=2,
            narrative_role=NarrativeRole.VALIDATION,
            reason=self.reason,
            novelty_distance=NoveltyDistance.CLOSE,
            narration_goal="connect the two tracks for the listener",
            evidence_ids=[f"{self.scene_id}-e{index}" for index in range(len(self.facts))],
        )

    def evidence(self) -> list[Evidence]:
        return [
            Evidence(
                id=f"{self.scene_id}-e{index}",
                claim_or_excerpt=fact,
                source_url="https://example.test/fixture",
                source_provider="fixture",
                confidence=0.8,
                query=self.topic,
            )
            for index, fact in enumerate(self.facts)
        ]

    def slot(self) -> NarrationSlotContext:
        placement = (
            NarrationSlotPlacement.AFTER_FINAL_TRACK
            if self.is_final
            else NarrationSlotPlacement.BEFORE_TRACK
        )
        return NarrationSlotContext(
            slot_id=f"scene-{self.scene_id}",
            chapter_index=2,
            placement=placement,
            allowed_block_kinds=[self.kind],
            chapter_track=self.upcoming or self.just_played,
            just_played_track=self.just_played,
            upcoming_track=self.upcoming,
            is_opening=self.is_opening,
            is_final=self.is_final,
        )


def _track(ref: str, artist: str, title: str) -> ResolvedTrack:
    return ResolvedTrack(track_ref=f"fixture:{ref}", canonical_artist=artist, canonical_title=title)


SCENES: tuple[NarrationScene, ...] = (
    NarrationScene(
        "hisaishi-solo",
        "久石让的钢琴世界，不止吉卜力",
        RadioScriptBlockKind.TRACK_INTRO,
        _track("h1", "久石譲", "天空の城ラピュタ"),
        _track("h2", "久石譲", "Summer"),
        (
            "《Summer》是久石让为北野武的电影《菊次郎的夏天》（1999）写的主题曲，以钢琴为主，旋律简单而反复。",
            "《天空之城》（1986）是宫崎骏与久石让合作的第二部长片。",
        ),
        station=StationId.PORTRAIT,
    ),
    NarrationScene(
        "casals-preludes",
        "巴赫无伴奏大提琴组曲的不同演绎",
        RadioScriptBlockKind.TRANSITION,
        _track("c1", "Pablo Casals", "Cello Suite No. 1 in G Major, BWV 1007: IV. Sarabande"),
        _track("c2", "Pablo Casals", "Suite No. 5 in C minor: I. Prelude (Adagio)"),
        (
            "卡萨尔斯在 20 世纪初把巴赫的无伴奏大提琴组曲带回了音乐会舞台。",
            "他在 1936 至 1939 年间录下了完整的六首组曲。",
        ),
        station=StationId.CRATE,
    ),
    NarrationScene(
        "postrock-bridge",
        "后摇滚入门：从 Mogwai 到 Explosions in the Sky",
        RadioScriptBlockKind.TRANSITION,
        _track("p1", "Mogwai", "Remurdered"),
        _track("p2", "Explosions In The Sky", "Your Hand in Mine"),
        (
            "Mogwai 来自苏格兰格拉斯哥，1995 年成军。",
            "Explosions in the Sky 来自美国得克萨斯州奥斯汀，1999 年成军，几乎只做器乐。",
        ),
        station=StationId.LINEAGE,
    ),
    NarrationScene(
        "citypop-yamashita",
        "深夜独享：日本 City Pop",
        RadioScriptBlockKind.TRACK_INTRO,
        _track("y1", "山下達郎", "SPARKLE"),
        _track("y2", "山下達郎", "Jody"),
        (
            "《Sparkle》是山下达郎 1982 年专辑《FOR YOU》的第一首。",
            "山下达郎早年在 Sugar Babe 乐队，1975 年出过专辑《SONGS》，大贯妙子也是成员。",
        ),
        station=StationId.CASUAL,
    ),
    NarrationScene(
        "utada-japanese-artist",
        "九十年代日本流行",
        RadioScriptBlockKind.TRANSITION,
        _track("u1", "宇多田ヒカル", "Automatic"),
        _track("u2", "宇多田ヒカル", "First Love"),
        (
            "《Automatic》是宇多田光 1998 年的出道单曲。",
            "专辑《First Love》1999 年发行。",
        ),
        station=StationId.PORTRAIT,
    ),
    NarrationScene(
        "miles-modal",
        "爵士乐入门：调式爵士",
        RadioScriptBlockKind.TRACK_INTRO,
        _track("m1", "Miles Davis", "So What"),
        _track("m2", "Miles Davis", "Blue in Green"),
        ("两首歌都收在 1959 年的专辑《Kind of Blue》里。",),
        station=StationId.LINEAGE,
    ),
    NarrationScene(
        "chinese-no-evidence",
        "陈绮贞的歌",
        RadioScriptBlockKind.TRANSITION,
        _track("z1", "陈绮贞", "旅行的意义"),
        _track("z2", "陈绮贞", "躺在你的衣柜"),
        (),
        reason="two songs by the same singer-songwriter, a quieter one next",
        station=StationId.CASUAL,
    ),
    NarrationScene(
        "opening-postrock",
        "后摇滚入门：从 Mogwai 到 Explosions in the Sky",
        RadioScriptBlockKind.INTRO,
        None,
        _track("p0", "Mogwai", "Take Me Somewhere Nice"),
        ("Mogwai 来自苏格兰格拉斯哥，1995 年成军，以长时间的器乐推进著称。",),
        window_seconds=12,
        is_opening=True,
        station=StationId.LINEAGE,
    ),
    NarrationScene(
        "opening-citypop",
        "深夜独享：日本 City Pop",
        RadioScriptBlockKind.INTRO,
        None,
        _track("y0", "山下達郎", "RIDE ON TIME"),
        ("《Ride on Time》是山下达郎 1980 年的专辑和同名单曲。",),
        window_seconds=12,
        is_opening=True,
        station=StationId.CASUAL,
    ),
    NarrationScene(
        "outro-casals",
        "巴赫无伴奏大提琴组曲的不同演绎",
        RadioScriptBlockKind.OUTRO,
        _track("c9", "Pablo Casals", "Overture (Suite) No. 3 in D Major, BWV 1068: II. Air"),
        None,
        (
            "卡萨尔斯在 1936 至 1939 年间录下了完整的六首组曲。",
            "巴赫的无伴奏大提琴组曲没有留下手稿，今天的演奏都依据抄本。",
        ),
        window_seconds=25,
        is_final=True,
        previous_context="本期放了卡萨尔斯演奏的前奏曲、萨拉班德和咏叹调。",
        station=StationId.CRATE,
    ),
)
