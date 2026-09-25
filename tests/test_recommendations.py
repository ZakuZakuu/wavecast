from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wavecast.models.episode import CoverParams
from wavecast.proposals import InMemoryProgramProposalRepository, ProgramProposal
from wavecast.recommendations import (
    DeterministicRecommendationPlanner,
    InMemoryProgramIdeaRepository,
    RecommendationService,
    UserContextAggregator,
)
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
            _proposal("other-user-program", "不应泄漏的节目", "Private Artist"),
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
    from wavecast.recommendations import UserContext

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
