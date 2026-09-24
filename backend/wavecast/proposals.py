from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from hashlib import sha1
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from wavecast.models.episode import CoverParams, EpisodeSeed, utc_now


class DurationIntent(StrEnum):
    AUTO = "AUTO"
    SHORT = "SHORT"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class ProposalGenerationRequest(BaseModel):
    prompt: str = Field(min_length=2, max_length=500)
    duration_intent: DurationIntent = DurationIntent.AUTO
    count: int = Field(default=1, ge=1, le=12)
    taste_context: str | None = Field(default=None, max_length=1000)


class ProgramProposal(BaseModel):
    """Cheap editorial promise shown before expensive episode materialization."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=500)
    short_description: str = Field(min_length=1, max_length=500)
    estimated_duration_seconds: int = Field(gt=0)
    opening_track_ref: str = Field(min_length=1, max_length=500)
    opening_track_title: str = Field(min_length=1, max_length=300)
    opening_track_artist: str = Field(min_length=1, max_length=300)
    cover: CoverParams
    editorial_route: list[str] = Field(min_length=2, max_length=8)
    genre_tags: list[str] = Field(default_factory=list, max_length=8)
    mood_tags: list[str] = Field(default_factory=list, max_length=8)
    anchor_artists: list[str] = Field(default_factory=list, max_length=8)
    generation_profile: str = Field(default="balanced", min_length=1, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)

    def to_episode_seed(self) -> EpisodeSeed:
        return EpisodeSeed(
            id=self.id,
            title=self.title,
            topic=self.topic,
            short_description=self.short_description,
            estimated_duration_seconds=self.estimated_duration_seconds,
            opening_track_ref=self.opening_track_ref,
            opening_track_title=self.opening_track_title,
            opening_track_artist=self.opening_track_artist,
            cover=self.cover,
            generation_profile=self.generation_profile,
            created_at=self.created_at,
        )

    @classmethod
    def from_episode_seed(cls, seed: EpisodeSeed) -> ProgramProposal:
        return cls(
            id=seed.id,
            title=seed.title,
            topic=seed.topic,
            short_description=seed.short_description,
            estimated_duration_seconds=seed.estimated_duration_seconds,
            opening_track_ref=seed.opening_track_ref,
            opening_track_title=seed.opening_track_title,
            opening_track_artist=seed.opening_track_artist,
            cover=seed.cover,
            editorial_route=["开场", "展开", "转折", "收尾"],
            genre_tags=[],
            mood_tags=[],
            anchor_artists=[],
            generation_profile=seed.generation_profile,
            created_at=seed.created_at,
        )


class ProgramProposalBatch(BaseModel):
    proposals: list[ProgramProposal]


class ProgramProposalGenerator(Protocol):
    async def generate(self, request: ProposalGenerationRequest) -> list[ProgramProposal]: ...


class ProgramProposalRepository(Protocol):
    def save_many(self, proposals: Iterable[ProgramProposal]) -> None: ...

    def get(self, proposal_id: str) -> ProgramProposal | None: ...


class InMemoryProgramProposalRepository:
    def __init__(self) -> None:
        self._proposals: dict[str, ProgramProposal] = {}

    def save_many(self, proposals: Iterable[ProgramProposal]) -> None:
        for proposal in proposals:
            self._proposals[proposal.id] = proposal

    def get(self, proposal_id: str) -> ProgramProposal | None:
        return self._proposals.get(proposal_id)


_DURATION_SECONDS = {
    DurationIntent.AUTO: 36 * 60,
    DurationIntent.SHORT: 22 * 60,
    DurationIntent.STANDARD: 42 * 60,
    DurationIntent.DEEP: 72 * 60,
}

_PALETTES: tuple[tuple[str, str], ...] = (
    ("#173b57", "#ef6757"),
    ("#2c2148", "#b677ff"),
    ("#19455c", "#f1b86a"),
    ("#4b2437", "#f07878"),
    ("#123c36", "#8fd3b6"),
)

_FAMILIES = ("editorial", "waveform", "signal", "geometry")

_THEME_RULES: tuple[
    tuple[tuple[str, ...], str, list[str], list[str], list[str]],
    ...,
] = (
    (
        ("爵士", "jazz", "bossa"),
        "雨夜爵士",
        ["Jazz", "Bossa", "Late Night"],
        ["夜晚", "松弛", "城市"],
        ["先让夜色慢下来", "从经典声响找到入口", "沿着城市感向外走", "留一个柔和的收尾"],
    ),
    (
        ("city pop", "城市流行", "昭和"),
        "城市夜航",
        ["City Pop", "AOR", "Japanese Pop"],
        ["霓虹", "夜行", "复古"],
        ["从城市灯光出发", "听见节奏里的年代感", "把海岸线两边的声音接起来", "回到今天的夜晚"],
    ),
    (
        ("电子", "electronic", "synth", "合成器"),
        "合成器夜行",
        ["Electronic", "Synthpop", "Night Drive"],
        ["霓虹", "推进", "夜驾"],
        ["从一束合成器音色开始", "进入更明亮的节拍", "转向更深的电子纹理", "在余光里收束"],
    ),
    (
        ("r&b", "soul", "灵魂", "方大同"),
        "灵魂律动",
        ["R&B", "Soul", "Neo Soul"],
        ["温暖", "律动", "亲密"],
        ["先找到最自然的 groove", "听和声如何变得柔软", "把相邻的 Soul 线索串起来", "让最后一首慢慢落地"],
    ),
    (
        ("游戏", "game", "persona", "djmax"),
        "游戏世界的声音线索",
        ["Game Music", "Electronic", "Soundtrack"],
        ["叙事", "沉浸", "探索"],
        ["从熟悉的主题进入世界", "拆开声音里的角色感", "沿着相邻作品继续探索", "带着一个新线索离开"],
    ),
)


def _theme_for(prompt: str) -> tuple[str, list[str], list[str], list[str]]:
    folded = prompt.casefold()
    for needles, label, genres, moods, route in _THEME_RULES:
        if any(needle in folded for needle in needles):
            return label, genres, moods, route
    return (
        "此刻电台",
        ["Guided Listening"],
        ["探索", "陪伴"],
        ["从你的描述出发", "找到第一条声音线索", "向相邻的风格展开", "把旅程轻轻收回来"],
    )


def _prompt_excerpt(prompt: str, *, limit: int = 26) -> str:
    compact = " ".join(prompt.strip().split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


class DeterministicMockProgramProposalGenerator:
    """Credential-free proposal generator used to validate product lifecycle and contracts."""

    async def generate(self, request: ProposalGenerationRequest) -> list[ProgramProposal]:
        label, genres, moods, route = _theme_for(request.prompt)
        proposals: list[ProgramProposal] = []
        for index in range(request.count):
            digest = sha1(
                f"{request.prompt}|{request.duration_intent}|{index}".encode()
            ).hexdigest()
            seed = int(digest[:8], 16)
            palette = _PALETTES[seed % len(_PALETTES)]
            family = _FAMILIES[(seed // len(_PALETTES)) % len(_FAMILIES)]
            suffix = "" if request.count == 1 else f" · {index + 1}"
            excerpt = _prompt_excerpt(request.prompt)
            proposals.append(
                ProgramProposal(
                    id=f"proposal-{digest[:16]}",
                    title=f"{label}{suffix}",
                    topic=request.prompt.strip(),
                    short_description=f"从“{excerpt}”出发，排一条先能听、再慢慢展开的声音路线。",
                    estimated_duration_seconds=_DURATION_SECONDS[request.duration_intent],
                    opening_track_ref="mock:opening",
                    opening_track_title="Neon First Light",
                    opening_track_artist="Mira Fields",
                    cover=CoverParams(family=family, seed=seed % 1000, palette=palette),
                    editorial_route=list(route),
                    genre_tags=list(genres),
                    mood_tags=list(moods),
                    anchor_artists=["Mira Fields"],
                )
            )
        return proposals
