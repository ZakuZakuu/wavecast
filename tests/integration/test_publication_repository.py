"""The publication store keeps the same promises in memory and in Postgres."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.models.episode import CoverParams
from wavecast.publishing import (
    LIVE_STATUSES,
    ProgrammeSnapshot,
    Publication,
    PublicationStatus,
    Visibility,
    new_publication_id,
    short_code,
)
from wavecast.storage import (
    InMemoryPublicationRepository,
    PostgresPublicationRepository,
    PublicationConflictError,
)
from wavecast.storage.publications import published_programmes_table

DATABASE_URL = os.getenv("WAVECAST_TEST_DATABASE_URL")


@pytest.fixture(params=["memory", "postgres"])
def repository(request):
    if request.param == "memory":
        yield InMemoryPublicationRepository()
        return
    if not DATABASE_URL:
        pytest.skip("set WAVECAST_TEST_DATABASE_URL to run Postgres integration tests")
    repo = PostgresPublicationRepository(DATABASE_URL)
    yield repo
    repo.close()


def make(episode_id: str | None = None, *, owner="owner-a", user: str | None = None, status=PublicationStatus.PREPARING) -> Publication:
    identifier = new_publication_id()
    now = datetime.now(UTC)
    return Publication(
        id=identifier, code=short_code(identifier), source_episode_id=episode_id or f"episode-{uuid4().hex}",
        owner_listener_id=owner, owner_user_id=user, status=status,
        programme=ProgrammeSnapshot(
            title="节目", description="d", estimated_duration_seconds=600,
            opening_track_title="Song", opening_track_artist="Artist",
            cover=CoverParams(family="f", seed=1, palette=("#000000", "#ffffff")),
        ),
        created_at=now, updated_at=now,
    )


@pytest.fixture(autouse=True)
def clean_postgres(repository):
    yield
    if isinstance(repository, PostgresPublicationRepository):
        async def wipe() -> None:
            engine = create_async_engine(DATABASE_URL)
            async with engine.begin() as connection:
                await connection.execute(delete(published_programmes_table).where(
                    published_programmes_table.c.owner_listener_id.like("owner-%")
                ))
            await engine.dispose()
        asyncio.run(wipe())


def test_a_publication_is_found_by_id_code_and_episode(repository) -> None:
    created = repository.create(make())
    assert repository.get(created.id) == created
    assert repository.get_by_code(created.code).id == created.id
    assert repository.get_for_episode(created.source_episode_id).id == created.id
    assert repository.get("pub-nope") is None and repository.get_by_code("0000000000") is None


def test_an_episode_has_one_publication(repository) -> None:
    first = repository.create(make("episode-shared-" + uuid4().hex))
    with pytest.raises(PublicationConflictError):
        repository.create(make(first.source_episode_id))


def test_an_update_only_applies_from_the_expected_status(repository) -> None:
    created = repository.create(make())
    moved = repository.update(created.id, only_from={PublicationStatus.PREPARING}, status=PublicationStatus.MIXING)
    assert moved is not None and moved.status is PublicationStatus.MIXING
    # A second worker looking at the old state does not get to move it again.
    assert repository.update(created.id, only_from={PublicationStatus.PREPARING}, status=PublicationStatus.MIXING) is None
    done = repository.update(
        created.id, status=PublicationStatus.PUBLISHED, asset_keys=["a", "b"], bytes_total=123,
        audio_seconds=598.5, plan_fingerprint="fp", published_at=datetime.now(UTC), visibility=Visibility.PUBLIC,
    )
    assert done.asset_keys == ["a", "b"] and done.bytes_total == 123 and done.visibility is Visibility.PUBLIC
    assert repository.get(created.id).audio_seconds == 598.5
    assert repository.update("pub-nope", status=PublicationStatus.FAILED) is None


def test_published_audio_is_pinned_until_it_fails(repository) -> None:
    published = repository.create(make(status=PublicationStatus.PUBLISHED))
    repository.update(published.id, bytes_total=1000)
    revoked = repository.create(make(status=PublicationStatus.REVOKED))
    repository.update(revoked.id, bytes_total=500)
    failed = repository.create(make(status=PublicationStatus.FAILED))
    repository.update(failed.id, bytes_total=999)

    pinned = repository.pinned_episode_ids()

    assert {published.source_episode_id, revoked.source_episode_id} <= pinned
    assert failed.source_episode_id not in pinned
    # Revoked audio still counts against the budget: copies play it.
    total = repository.pinned_bytes()
    assert total >= 1500
    repository.update(revoked.id, status=PublicationStatus.FAILED)
    assert repository.pinned_bytes() == total - 500


def test_owners_are_found_by_listener_or_account(repository) -> None:
    mine = repository.create(make(owner="owner-guest-" + uuid4().hex))
    theirs = repository.create(make(owner="owner-other-" + uuid4().hex, user="user-" + uuid4().hex))
    by_account = repository.list_for_owner("someone-else", theirs.owner_user_id)
    assert [item.id for item in by_account] == [theirs.id]
    assert [item.id for item in repository.list_for_owner(mine.owner_listener_id, None)] == [mine.id]
    assert repository.count_for_owner(mine.owner_listener_id, None, LIVE_STATUSES) == 1
    assert repository.count_for_owner(mine.owner_listener_id, None, {PublicationStatus.PUBLISHED}) == 0


def test_a_listener_is_counted_once_per_programme(repository) -> None:
    created = repository.create(make())
    assert repository.record_listen(created.id, "user:1") is True
    assert repository.record_listen(created.id, "user:1") is False
    assert repository.record_listen(created.id, "guest:2") is True
    assert repository.listen_count(created.id) == 2
