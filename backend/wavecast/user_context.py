"""Small durable user-context contracts for explainable recommendation inputs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Genre(StrEnum):
    CITY_POP = "City Pop"
    R_AND_B = "R&B"
    JAZZ = "Jazz"
    ELECTRONIC = "Electronic"
    HIP_HOP = "Hip-Hop"
    ROCK = "Rock"
    CLASSICAL = "Classical"


class Mood(StrEnum):
    CHILL = "Chill"
    FOCUS = "Focus"
    LATE_NIGHT = "Late Night"
    DISCOVERY = "Discovery"


class DiscoveryLevel(StrEnum):
    SAFE = "SAFE"
    BALANCED = "BALANCED"
    ADVENTUROUS = "ADVENTUROUS"


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    genres: list[Genre] = Field(default_factory=list, max_length=7)
    artists: list[str] = Field(default_factory=list, max_length=20)
    moods: list[Mood] = Field(default_factory=list, max_length=4)
    contexts: list[str] = Field(default_factory=list, max_length=20)
    discovery_level: DiscoveryLevel = DiscoveryLevel.BALANCED
    onboarding_completed: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    genres: list[Genre] = Field(default_factory=list, max_length=7)
    artists: list[str] = Field(default_factory=list, max_length=20)
    moods: list[Mood] = Field(default_factory=list, max_length=4)
    contexts: list[str] = Field(default_factory=list, max_length=20)
    discovery_level: DiscoveryLevel = DiscoveryLevel.BALANCED
    onboarding_completed: bool = True


class UserPreferencesRepository(Protocol):
    def get(self, user_id: str) -> UserPreferences | None: ...

    def save(self, preferences: UserPreferences) -> UserPreferences: ...

    def delete(self, user_id: str) -> bool: ...


class InMemoryUserPreferencesRepository:
    def __init__(self) -> None:
        self._preferences: dict[str, UserPreferences] = {}

    def get(self, user_id: str) -> UserPreferences | None:
        return self._preferences.get(user_id)

    def save(self, preferences: UserPreferences) -> UserPreferences:
        self._preferences[preferences.user_id] = preferences
        return preferences

    def delete(self, user_id: str) -> bool:
        return self._preferences.pop(user_id, None) is not None


class UserEventType(StrEnum):
    PLAY_START = "PLAY_START"
    PLAY_COMPLETE = "PLAY_COMPLETE"
    LIKE = "LIKE"
    FAVORITE = "FAVORITE"
    SAVE = "SAVE"
    SKIP = "SKIP"


class UserEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: UserEventType
    program_id: str | None = Field(default=None, max_length=128)
    episode_id: str | None = Field(default=None, max_length=128)


class UserEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    event_type: UserEventType
    program_id: str | None = None
    episode_id: str | None = None
    occurred_at: datetime


class UserEventRepository(Protocol):
    def create(self, event: UserEvent) -> UserEvent: ...

    def list_for_user(self, user_id: str, *, limit: int = 100) -> list[UserEvent]: ...


class InMemoryUserEventRepository:
    def __init__(self) -> None:
        self._events: list[UserEvent] = []

    def create(self, event: UserEvent) -> UserEvent:
        self._events.append(event)
        return event

    def list_for_user(self, user_id: str, *, limit: int = 100) -> list[UserEvent]:
        events = sorted(
            (event for event in self._events if event.user_id == user_id),
            key=lambda event: event.occurred_at,
            reverse=True,
        )
        return events[:limit]


class UserEventService:
    def __init__(self, repository: UserEventRepository) -> None:
        self.repository = repository

    def record(self, *, user_id: str, event: UserEventInput) -> UserEvent:
        return self.repository.create(
            UserEvent(
                id=uuid4().hex,
                user_id=user_id,
                event_type=event.event_type,
                program_id=event.program_id,
                episode_id=event.episode_id,
                occurred_at=datetime.now(UTC),
            )
        )
