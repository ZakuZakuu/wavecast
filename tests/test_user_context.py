from __future__ import annotations

import pytest
from pydantic import ValidationError
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


def test_user_preferences_have_safe_empty_defaults_and_closed_vocabulary() -> None:
    preferences = UserPreferences(user_id="listener-1")

    assert preferences.genres == []
    assert preferences.artists == []
    assert preferences.moods == []
    assert preferences.contexts == []
    assert preferences.discovery_level is DiscoveryLevel.BALANCED
    assert preferences.onboarding_completed is False
    assert Genre.CITY_POP.value == "City Pop"
    assert Mood.LATE_NIGHT.value == "Late Night"

    with pytest.raises(ValidationError):
        UserPreferences(user_id="listener-1", genres=["Metal"])


def test_preferences_repository_saves_replaces_and_deletes_by_user() -> None:
    repository = InMemoryUserPreferencesRepository()
    preferences = UserPreferences(
        user_id="user-a",
        genres=[Genre.R_AND_B],
        moods=[Mood.CHILL],
        onboarding_completed=True,
    )

    repository.save(preferences)

    assert repository.get("user-a") == preferences
    assert repository.get("user-b") is None
    assert repository.delete("user-a") is True
    assert repository.get("user-a") is None
    assert repository.delete("user-a") is False


def test_event_service_records_only_product_event_fields() -> None:
    repository = InMemoryUserEventRepository()
    service = UserEventService(repository)
    created = service.record(
        user_id="user-a",
        event=UserEventInput(
            event_type=UserEventType.PLAY_START,
            program_id="program-1",
            episode_id="episode-1",
        ),
    )

    assert created.user_id == "user-a"
    assert created.event_type is UserEventType.PLAY_START
    assert created.program_id == "program-1"
    assert created.episode_id == "episode-1"
    assert repository.list_for_user("user-a") == [created]
    assert repository.list_for_user("user-b") == []

    with pytest.raises(ValidationError):
        UserEventInput(event_type="PROVIDER_RESPONSE", raw_prompt="private")
