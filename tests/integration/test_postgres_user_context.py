from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.storage.user_context import (
    PostgresUserEventRepository,
    PostgresUserPreferencesRepository,
    user_events_table,
    user_preferences_table,
)
from wavecast.user_context import (
    DiscoveryLevel,
    UserEventInput,
    UserEventService,
    UserEventType,
    UserPreferences,
)

DATABASE_URL = os.getenv("WAVECAST_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set WAVECAST_TEST_DATABASE_URL to run Postgres integration tests"
)


def test_preferences_and_product_events_are_durable() -> None:
    assert DATABASE_URL is not None
    user_id = f"user-context-test-{uuid4().hex}"
    preferences = UserPreferences(
        user_id=user_id,
        genres=["City Pop"],
        moods=["Late Night"],
        discovery_level=DiscoveryLevel.ADVENTUROUS,
        onboarding_completed=True,
    )

    async def cleanup() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as connection:
            await connection.execute(
                delete(user_events_table).where(user_events_table.c.user_id == user_id)
            )
            await connection.execute(
                delete(user_preferences_table).where(user_preferences_table.c.user_id == user_id)
            )
        await engine.dispose()

    asyncio.run(cleanup())
    preference_repo = PostgresUserPreferencesRepository(DATABASE_URL)
    preference_repo.save(preferences)
    preference_repo.close()
    recovered = PostgresUserPreferencesRepository(DATABASE_URL)
    assert recovered.get(user_id) == preferences

    event_repo = PostgresUserEventRepository(DATABASE_URL)
    service = UserEventService(event_repo)
    event = service.record(
        user_id=user_id,
        event=UserEventInput(
            event_type=UserEventType.PLAY_START,
            program_id="program-test",
            episode_id="episode-test",
        ),
    )
    assert event_repo.list_for_user(user_id, limit=1) == [event]
    assert event_repo.list_for_user(f"{user_id}-other") == []
    event_repo.close()

    async def read_event() -> dict[str, object] | None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    select(user_events_table).where(user_events_table.c.id == event.id)
                )
            ).first()
        await engine.dispose()
        return dict(row._mapping) if row else None

    try:
        assert asyncio.run(read_event()) == {
            "id": event.id,
            "user_id": user_id,
            "event_type": "PLAY_START",
            "program_id": "program-test",
            "episode_id": "episode-test",
            "occurred_at": event.occurred_at,
        }
    finally:
        recovered.delete(user_id)
        asyncio.run(cleanup())
        recovered.close()
