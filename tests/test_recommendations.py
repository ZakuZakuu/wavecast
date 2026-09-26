from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import sleep

from pydantic import BaseModel
from wavecast.models.episode import CoverParams
from wavecast.proposals import InMemoryProgramProposalRepository, ProgramProposal
from wavecast.recommendations import (
    DeterministicRecommendationPlanner,
    InMemoryProgramIdeaRepository,
    ProgramIdea,
    ProgramIdeaDraft,
    ProgramIdeaDraftBatch,
    ProviderBackedRecommendationPlanner,
    RecommendationService,
    UserContext,
    UserContextAggregator,
)
from wavecast.providers.errors import ProviderUnavailableError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.user_context import (
    DiscoveryLevel,
    Genre,
    InMemoryUserEventRepository,
    InMemoryUserPreferencesRepository,
    Mood,
    UserEventInput,
    UserEventService,
    UserEventType,
    UserPreferences,
)


def _proposal(program_id: str, topic: str, artist: str) -> ProgramProposal:
    return ProgramProposal(
        id=program_id,
        title=f"Program: {topic}",
        topic=topic,
        short_description=f"A route through {topic}",
        estimated_duration_seconds=1800,
        opening_track_ref="mock:opening",
        opening_track_title="Opening",
        opening_track_artist=artist,
        cover=CoverParams(family="editorial", seed=1, palette=("#102030", "#f0a050")),
        editorial_route=["opening", "discovery"],
        genre_tags=["R&B"],
        mood_tags=["Late Night"],
        anchor_artists=[artist],
    )


def test_context_aggregates_preferences_recent_events_favorites_and_created_programs() -> None:
    preferences = InMemoryUserPreferencesRepository()
    preferences.save(
        UserPreferences(
            user_id="user-a",
            genres=[Genre.CITY_POP],
            moods=[Mood.LATE_NIGHT],
            artists=["Mariya Takeuchi"],
            contexts=["雨夜散步"],
            discovery_level=DiscoveryLevel.ADVENTUROUS,
        )
    )
    events = InMemoryUserEventRepository()
    event_service = UserEventService(events)
    event_service.record(
        user_id="user-a",
        event=UserEventInput(event_type=UserEventType.FAVORITE, program_id="favorite-program"),
    )
    event_service.record(
        user_id="user-a",
        event=UserEventInput(event_type=UserEventType.PLAY_COMPLETE, program_id="recent-program"),
    )
    event_service.record(
        user_id="user-b",
        event=UserEventInput(event_type=UserEventType.FAVORITE, program_id="other-user-program"),
    )
    proposals = InMemoryProgramProposalRepository()
    proposals.save_many(
        [
            _proposal("favorite-program", "收藏的 Neo Soul 路线", "Jill Scott"),
            _proposal("recent-program", "最近听过的 City Pop 路线", "Anri"),
            _proposal("created-program", "用户自己创建的节目", "Mariya Takeuchi"),
        ],
        owner_user_id="user-a",
    )
    proposals.save_many(
        [_proposal("other-user-program", "不应泄漏的节目", "Private Artist")],
        owner_user_id="user-b",
    )
    aggregator = UserContextAggregator(
        preferences,
        events,
        proposals,
        public_program_lookup=lambda _program_id: None,
    )

    context = aggregator.build("user-a")

    assert context.genres == ["City Pop"]
    assert context.moods == ["Late Night"]
    assert context.contexts == ["雨夜散步"]
    assert context.discovery_level == 0.8
    assert "最近听过的 City Pop 路线" in context.recent_interests
    assert "用户自己创建的节目" in context.recent_interests
    assert "收藏的 Neo Soul 路线" in context.favorite_interests
    assert "Jill Scott" in context.preferred_artists
    assert "Private Artist" not in context.preferred_artists


def test_deterministic_planner_uses_preferences_and_recent_context() -> None:
    ideas = DeterministicRecommendationPlanner().generate_program_ideas(
        UserContext(
            user_id="user-a",
            genres=["R&B"],
            moods=["Focus"],
            recent_interests=["Persona Jazz"],
            favorite_interests=["Neo Soul"],
            preferred_artists=["Musiq Soulchild"],
            discovery_level=0.8,
        )
    )

    assert len(ideas) == 3
    assert any("R&B" in idea.title and "Focus" in idea.title for idea in ideas)
    assert any("Persona Jazz" in idea.title for idea in ideas)
    assert any("Neo Soul" in idea.reason for idea in ideas)

class _RecommendationLLM:
    def __init__(
        self,
        batch: ProgramIdeaDraftBatch | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.batch = batch
        self.error = error
        self.prompt = ""
        self.transport: StructuredTransport | None = None
        self.profile: InferenceProfile | None = None
        self.stage: str | None = None
        self.closed = False

    async def structured(
        self,
        prompt: str,
        output_type: type[BaseModel],
        *,
        transport: StructuredTransport,
        profile: InferenceProfile,
        stage: str | None = None,
    ) -> BaseModel:
        assert output_type is ProgramIdeaDraftBatch
        self.prompt = prompt
        self.transport = transport
        self.profile = profile
        self.stage = stage
        if self.error is not None:
            raise self.error
        assert self.batch is not None
        return self.batch

    async def aclose(self) -> None:
        self.closed = True


def test_provider_backed_planner_uses_compact_user_context_without_identity() -> None:
    llm = _RecommendationLLM(
        ProgramIdeaDraftBatch(
            ideas=[
                ProgramIdeaDraft(
                    title="从 Neo-Soul 的松弛感拐进 Broken Beat",
                    description="从熟悉的 R&B 和 Soul 出发，逐渐把节奏切得更碎、更有弹性。",
                    reason="结合 R&B、Chill 与较高探索偏好。",
                    tags=["R&B", "Neo Soul", "Broken Beat"],
                ),
                ProgramIdeaDraft(
                    title="方大同之后，往更深的 Soul 和声走",
                    description="从熟悉的华语 R&B 入口，沿着和声与 groove 的线索向外延伸。",
                    reason="结合艺人偏好与 R&B 风格信号。",
                    tags=["R&B", "Soul"],
                ),
                ProgramIdeaDraft(
                    title="夜里不降速：把 Chill R&B 推向更亮的律动",
                    description="保留松弛氛围，但逐步加入更明确的鼓点与舞曲感。",
                    reason="来自 Chill 氛围与探索倾向。",
                    tags=["R&B", "Chill", "Discovery"],
                ),
            ]
        )
    )
    planner = ProviderBackedRecommendationPlanner(lambda: llm)

    ideas = planner.generate_program_ideas(
        UserContext(
            user_id="user-secret-id",
            genres=["R&B"],
            moods=["Chill"],
            contexts=["夜间散步"],
            preferred_artists=["方大同"],
            discovery_level=0.8,
        )
    )

    assert len(ideas) == 3
    assert ideas[0].title.startswith("从 Neo-Soul")
    assert '"genres": ["R&B"]' in llm.prompt
    assert '"preferred_artists": ["方大同"]' in llm.prompt
    assert "user-secret-id" not in llm.prompt
    assert llm.transport is StructuredTransport.RESPONSES_JSON_SCHEMA
    assert llm.profile is InferenceProfile.FAST
    assert llm.stage == "recommendation_planner"
    assert llm.closed


def test_provider_backed_planner_falls_back_without_breaking_inventory() -> None:
    llm = _RecommendationLLM(error=ProviderUnavailableError("temporary outage"))
    planner = ProviderBackedRecommendationPlanner(lambda: llm)

    ideas = planner.generate_program_ideas(
        UserContext(
            user_id="user-a",
            genres=["R&B"],
            moods=["Chill"],
            discovery_level=0.5,
        )
    )

    assert len(ideas) >= 2
    assert any("R&B" in idea.title for idea in ideas)
    assert llm.closed


def test_planner_source_change_replaces_cached_heuristic_inventory() -> None:
    ideas = InMemoryProgramIdeaRepository()
    now = datetime(2026, 9, 26, tzinfo=UTC)
    old = ProgramIdea(
        id="old-heuristic",
        user_id="user-a",
        title="旧模板推荐",
        description="旧的 deterministic inventory",
        reason="旧推荐",
        source="heuristic",
        created_at=now,
    )
    ideas.save_many([old])

    class NewPlanner:
        source = "deepseek_planner"

        def generate_program_ideas(self, context: UserContext) -> list[ProgramIdeaDraft]:
            del context
            return [
                ProgramIdeaDraft(
                    title=f"AI idea {index}",
                    description="更具体的节目方向",
                    reason="新的 planner source",
                    tags=["R&B"],
                )
                for index in range(3)
            ]

    service = RecommendationService(
        UserContextAggregator(
            InMemoryUserPreferencesRepository(),
            InMemoryUserEventRepository(),
            InMemoryProgramProposalRepository(),
        ),
        NewPlanner(),
        ideas,
        clock=lambda: now,
    )

    refreshed = service.inventory_for_user("user-a")

    assert len(refreshed) == 3
    assert {idea.source for idea in refreshed} == {"deepseek_planner"}
    assert "old-heuristic" not in {idea.id for idea in refreshed}



def test_refresh_is_bounded_per_user_and_proposal_seed_retains_reason() -> None:
    preferences = InMemoryUserPreferencesRepository()
    events = InMemoryUserEventRepository()
    proposals = InMemoryProgramProposalRepository()
    ideas = InMemoryProgramIdeaRepository()
    now = datetime(2026, 9, 25, tzinfo=UTC)
    service = RecommendationService(
        UserContextAggregator(preferences, events, proposals),
        DeterministicRecommendationPlanner(),
        ideas,
        refresh_interval=timedelta(hours=24),
        clock=lambda: now,
    )

    first = service.refresh_for_user("user-a")
    second = service.refresh_for_user("user-a")
    other_user = service.refresh_for_user("user-b")
    adapted = first[0].to_proposal_seed()

    assert [idea.id for idea in first] == [idea.id for idea in second]
    assert {idea.user_id for idea in ideas.list_for_user("user-a")} == {"user-a"}
    assert {idea.user_id for idea in other_user} == {"user-b"}
    assert adapted.recommendation_id == first[0].id
    assert adapted.reason == first[0].reason
    assert adapted.request.prompt.startswith(first[0].title)
    assert adapted.request.taste_context and first[0].reason in adapted.request.taste_context


def test_concurrent_refreshes_share_one_cooldown_window() -> None:
    preferences = InMemoryUserPreferencesRepository()
    events = InMemoryUserEventRepository()
    proposals = InMemoryProgramProposalRepository()
    ideas = InMemoryProgramIdeaRepository()
    now = datetime(2026, 9, 25, tzinfo=UTC)
    planner = DeterministicRecommendationPlanner()
    call_count = 0
    count_lock = Lock()

    class CountingPlanner:
        source = planner.source

        def generate_program_ideas(self, context):
            nonlocal call_count
            with count_lock:
                call_count += 1
            sleep(0.02)
            return planner.generate_program_ideas(context)

    service = RecommendationService(
        UserContextAggregator(preferences, events, proposals),
        CountingPlanner(),
        ideas,
        clock=lambda: now,
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: service.refresh_for_user("user-a"), range(4)))

    assert call_count == 1
    assert all([idea.id for idea in result] == [idea.id for idea in results[0]] for result in results)


def test_program_idea_repository_retains_only_latest_thirty_per_user() -> None:
    ideas = InMemoryProgramIdeaRepository()
    created = [
        ProgramIdea(
            id=f"idea-{index:02}",
            user_id="user-a",
            title=f"Idea {index}",
            description="Description",
            reason="Reason",
            created_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index),
        )
        for index in range(35)
    ]

    ideas.save_many(created)
    retained = ideas.list_for_user("user-a", limit=100)

    assert len(retained) == 30
    assert retained[0].id == "idea-34"
    assert retained[-1].id == "idea-05"


def test_inventory_refills_after_available_stock_falls_below_low_water() -> None:
    preferences = InMemoryUserPreferencesRepository()
    events = InMemoryUserEventRepository()
    proposals = InMemoryProgramProposalRepository()
    ideas = InMemoryProgramIdeaRepository()
    now = datetime(2026, 9, 26, tzinfo=UTC)
    service = RecommendationService(
        UserContextAggregator(preferences, events, proposals),
        DeterministicRecommendationPlanner(),
        ideas,
        clock=lambda: now,
    )

    first = service.inventory_for_user("user-a")
    assert len(first) >= 2

    claimed = service.claim_for_materialization("user-a", first[0].id)
    assert claimed is not None
    assert claimed.status.value == "USED"

    refilled = service.inventory_for_user("user-a")
    assert len(refilled) >= 2
    assert all(idea.status.value == "AVAILABLE" for idea in refilled)
    assert first[0].id not in {idea.id for idea in refilled}


def test_recommendation_claim_is_single_use_and_can_be_restored() -> None:
    service = RecommendationService(
        UserContextAggregator(
            InMemoryUserPreferencesRepository(),
            InMemoryUserEventRepository(),
            InMemoryProgramProposalRepository(),
        ),
        DeterministicRecommendationPlanner(),
        InMemoryProgramIdeaRepository(),
        clock=lambda: datetime(2026, 9, 26, tzinfo=UTC),
    )
    idea = service.inventory_for_user("user-a")[0]

    first_claim = service.claim_for_materialization("user-a", idea.id)
    second_claim = service.claim_for_materialization("user-a", idea.id)

    assert first_claim is not None
    assert second_claim is None
    assert service.restore_available("user-a", idea.id) is not None
    assert service.claim_for_materialization("user-a", idea.id) is not None
