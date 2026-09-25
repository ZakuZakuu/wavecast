"""Explainable user-context aggregation and lightweight program idea planning."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from wavecast.proposals import (
    DurationIntent,
    ProgramProposal,
    ProposalGenerationRequest,
)
from wavecast.user_context import (
    DiscoveryLevel,
    UserEvent,
    UserEventRepository,
    UserEventType,
    UserPreferences,
    UserPreferencesRepository,
)


class UserContext(BaseModel):
    """Compact private input to the planner; never returned by the API."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    genres: list[str] = Field(default_factory=list, max_length=7)
    moods: list[str] = Field(default_factory=list, max_length=4)
    contexts: list[str] = Field(default_factory=list, max_length=20)
    recent_interests: list[str] = Field(default_factory=list, max_length=12)
    favorite_interests: list[str] = Field(default_factory=list, max_length=12)
    preferred_artists: list[str] = Field(default_factory=list, max_length=20)
    discovery_level: float = Field(ge=0, le=1)


class ProgramIdeaStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    DISMISSED = "DISMISSED"
    USED = "USED"


class ProgramIdeaDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=12)


class ProgramIdea(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=32)
    user_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=12)
    source: str = Field(default="heuristic", min_length=1, max_length=32)
    status: ProgramIdeaStatus = ProgramIdeaStatus.AVAILABLE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_proposal_seed(
        self, duration_intent: DurationIntent = DurationIntent.STANDARD
    ) -> ProgramIdeaProposalSeed:
        prompt = f"{self.title}: {self.description}"[:500]
        context = f"{self.reason} Tags: {', '.join(self.tags)}"[:1000]
        return ProgramIdeaProposalSeed(
            recommendation_id=self.id,
            reason=self.reason,
            tags=self.tags,
            request=ProposalGenerationRequest(
                prompt=prompt,
                duration_intent=duration_intent,
                count=1,
                taste_context=context,
            ),
        )


class ProgramIdeaResponse(BaseModel):
    """Public candidate shape; repository ownership identifiers stay private."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    description: str
    reason: str
    tags: list[str]
    source: str
    status: ProgramIdeaStatus
    created_at: datetime

    @classmethod
    def from_idea(cls, idea: ProgramIdea) -> ProgramIdeaResponse:
        return cls(**idea.model_dump(exclude={"user_id"}))


class ProgramIdeaProposalSeed(BaseModel):
    """Adapter to the existing proposal flow while retaining recommendation context."""

    model_config = ConfigDict(frozen=True)

    recommendation_id: str
    reason: str
    tags: list[str]
    request: ProposalGenerationRequest


class RecommendationPlanner(Protocol):
    def generate_program_ideas(self, context: UserContext) -> list[ProgramIdeaDraft]: ...


class ProgramIdeaRepository(Protocol):
    def save_many(self, ideas: Iterable[ProgramIdea]) -> None: ...

    def list_for_user(self, user_id: str, *, limit: int = 12) -> list[ProgramIdea]: ...


class InMemoryProgramIdeaRepository:
    def __init__(self) -> None:
        self._ideas: list[ProgramIdea] = []

    def save_many(self, ideas: Iterable[ProgramIdea]) -> None:
        self._ideas.extend(ideas)

    def list_for_user(self, user_id: str, *, limit: int = 12) -> list[ProgramIdea]:
        matches = sorted(
            (idea for idea in self._ideas if idea.user_id == user_id),
            key=lambda idea: idea.created_at,
            reverse=True,
        )
        return matches[:limit]


class UserContextAggregator:
    def __init__(
        self,
        preferences: UserPreferencesRepository,
        events: UserEventRepository,
        proposals: ProposalContextRepository,
        *,
        public_program_lookup: Callable[[str], ProgramProposal | None] | None = None,
    ) -> None:
        self._preferences = preferences
        self._events = events
        self._proposals = proposals
        self._public_program_lookup = public_program_lookup or (lambda _program_id: None)

    def build(self, user_id: str) -> UserContext:
        preferences = self._preferences.get(user_id) or UserPreferences(user_id=user_id)
        events = self._events.list_for_user(user_id, limit=100)
        favorite_ids = _unique_event_program_ids(events, {UserEventType.FAVORITE})
        recent_ids = _unique_event_program_ids(
            events,
            {
                UserEventType.PLAY_START,
                UserEventType.PLAY_COMPLETE,
                UserEventType.SKIP,
                UserEventType.SAVE,
            },
        )

        favorites = self._resolve_programs(user_id, favorite_ids)
        recent = self._resolve_programs(user_id, recent_ids)
        created = self._proposals.list_for_user(user_id, limit=8)
        recent_interests = _unique(
            [
                *(_program_interest(program) for program in recent),
                *(_program_interest(program) for program in created),
            ],
            limit=12,
        )
        favorite_interests = _unique(
            [
                *(tag for program in favorites for tag in program.genre_tags),
                *(tag for program in favorites for tag in program.mood_tags),
                *(_program_interest(program) for program in favorites),
            ],
            limit=12,
        )
        preferred_artists = _unique(
            [
                *preferences.artists,
                *(artist for program in favorites for artist in program.anchor_artists),
            ],
            limit=20,
        )
        return UserContext(
            user_id=user_id,
            genres=[genre.value for genre in preferences.genres],
            moods=[mood.value for mood in preferences.moods],
            contexts=preferences.contexts,
            recent_interests=recent_interests,
            favorite_interests=favorite_interests,
            preferred_artists=preferred_artists,
            discovery_level={
                DiscoveryLevel.SAFE: 0.2,
                DiscoveryLevel.BALANCED: 0.5,
                DiscoveryLevel.ADVENTUROUS: 0.8,
            }[preferences.discovery_level],
        )

    def _resolve_programs(self, user_id: str, program_ids: list[str]) -> list[ProgramProposal]:
        resolved: list[ProgramProposal] = []
        for program_id in program_ids:
            program = self._proposals.get_for_user(user_id, program_id)
            if program is None:
                program = self._public_program_lookup(program_id)
            if program is not None:
                resolved.append(program)
        return resolved


class ProposalContextRepository(Protocol):
    def get_for_user(self, user_id: str, proposal_id: str) -> ProgramProposal | None: ...

    def list_for_user(self, user_id: str, *, limit: int = 20) -> list[ProgramProposal]: ...


class DeterministicRecommendationPlanner:
    """Small explainable MVP planner; a provider-backed planner can replace it later."""

    def generate_program_ideas(self, context: UserContext) -> list[ProgramIdeaDraft]:
        genre = context.genres[0] if context.genres else "Soul"
        mood = context.moods[0] if context.moods else "Late Night"
        preferred_context = context.contexts[0] if context.contexts else None
        recent = context.recent_interests[0] if context.recent_interests else None
        favorite = context.favorite_interests[0] if context.favorite_interests else None
        artist = context.preferred_artists[0] if context.preferred_artists else None
        discovery = "更大胆地" if context.discovery_level >= 0.7 else "循着熟悉的线索"

        ideas = [
            ProgramIdeaDraft(
                title=f"{mood}里的{genre}：再往外听一点",
                description=(
                    f"从你偏好的{genre}出发，沿着相邻声音展开一段适合"
                    f"{preferred_context or mood}的收听路线。"
                ),
                reason=(
                    f"根据你选择的风格「{genre}」和氛围「{mood}」生成。"
                    if preferred_context is None
                    else f"结合你填写的情境「{preferred_context}」与风格「{genre}」生成。"
                ),
                tags=_unique(
                    [genre, mood, *([preferred_context] if preferred_context else [])], limit=12
                ),
            )
        ]
        if recent:
            ideas.append(
                ProgramIdeaDraft(
                    title=f"从{recent}继续往外听",
                    description=f"从你最近接触的「{recent}」出发，寻找能自然接上的新音乐方向。",
                    reason=f"你最近听过或创建了「{recent}」，这条路线会{discovery}延伸。",
                    tags=_unique([genre, recent], limit=12),
                )
            )
        elif artist:
            ideas.append(
                ProgramIdeaDraft(
                    title=f"{artist}之后：沿着{genre}的线索",
                    description=f"从你喜欢的{artist}出发，听听{genre}里相近又不同的表达。",
                    reason=f"结合你填写的艺人偏好「{artist}」与风格「{genre}」。",
                    tags=[genre, artist],
                )
            )
        else:
            ideas.append(
                ProgramIdeaDraft(
                    title=f"换个角度听{genre}",
                    description=f"从熟悉的{genre}出发，找一条通往不同节奏与质感的音乐路线。",
                    reason=f"围绕你选择的「{genre}」提供一条可继续探索的节目方向。",
                    tags=[genre, "Discovery"],
                )
            )
        if favorite:
            ideas.append(
                ProgramIdeaDraft(
                    title=f"从收藏里的{genre}找一条新路线",
                    description=f"把你收藏过的「{favorite}」当作入口，连接到新的音乐线索。",
                    reason=f"参考你收藏相关节目留下的兴趣信号「{favorite}」。",
                    tags=_unique([genre, favorite, "Discovery"], limit=12),
                )
            )
        return ideas[:3]


class RecommendationService:
    def __init__(
        self,
        aggregator: UserContextAggregator,
        planner: RecommendationPlanner,
        repository: ProgramIdeaRepository,
        *,
        refresh_interval: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._aggregator = aggregator
        self._planner = planner
        self._repository = repository
        self._refresh_interval = refresh_interval
        self._clock = clock

    def list_for_user(self, user_id: str) -> list[ProgramIdea]:
        return self._repository.list_for_user(user_id, limit=12)

    def refresh_for_user(self, user_id: str) -> list[ProgramIdea]:
        existing = self.list_for_user(user_id)
        now = self._clock()
        if existing and now - existing[0].created_at < self._refresh_interval:
            return existing
        context = self._aggregator.build(user_id)
        ideas = [
            ProgramIdea(
                id=uuid4().hex,
                user_id=user_id,
                title=draft.title,
                description=draft.description,
                reason=draft.reason,
                tags=draft.tags,
                source="heuristic",
                created_at=now,
            )
            for draft in self._planner.generate_program_ideas(context)
        ]
        self._repository.save_many(ideas)
        return ideas


def _unique(values: Iterable[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
            if len(result) == limit:
                break
    return result


def _unique_event_program_ids(
    events: list[UserEvent], event_types: set[UserEventType]
) -> list[str]:
    return _unique(
        (
            event.program_id
            for event in events
            if event.event_type in event_types and event.program_id is not None
        ),
        limit=12,
    )


def _program_interest(program: ProgramProposal) -> str:
    return program.topic or program.title
