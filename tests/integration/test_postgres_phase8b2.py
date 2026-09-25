from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.models.episode import CoverParams, EpisodeSeed
from wavecast.orchestration.episode import EpisodeOrchestrator
from wavecast.proposals import ProgramProposal, ProposalPersistenceConflict
from wavecast.storage.episodes import PostgresEpisodeRepository, episodes_table
from wavecast.storage.library import PostgresUserLibraryRepository, user_library_entries
from wavecast.storage.proposals import PostgresProgramProposalRepository, program_proposals_table
from wavecast.storage.quota import (
    PostgresGenerationQuotaRepository,
    QuotaExceededError,
    quota_reservations,
)

DATABASE_URL = os.getenv("WAVECAST_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set WAVECAST_TEST_DATABASE_URL for PostgreSQL persistence tests"
)


def _cleanup(
    *, user_id: str | None = None, listener_id: str | None = None,
    episode_id: str | None = None, proposal_id: str | None = None,
) -> None:
    assert DATABASE_URL is not None

    async def run() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as connection:
            if user_id:
                await connection.execute(
                    delete(user_library_entries).where(user_library_entries.c.user_id == user_id)
                )
                await connection.execute(
                    delete(quota_reservations).where(quota_reservations.c.user_id == user_id)
                )
            if listener_id:
                await connection.execute(
                    delete(quota_reservations).where(quota_reservations.c.listener_id == listener_id)
                )
            if episode_id:
                await connection.execute(delete(episodes_table).where(episodes_table.c.id == episode_id))
            if proposal_id:
                await connection.execute(
                    delete(program_proposals_table).where(program_proposals_table.c.id == proposal_id)
                )
        await engine.dispose()

    asyncio.run(run())


def test_cloud_library_survives_repository_reconstruction_and_merge_is_idempotent() -> None:
    assert DATABASE_URL is not None
    user_id = f"library-test-{uuid4().hex}"
    payload = {
        "favoriteSeedIds": ["favorite-a"],
        "createdProgramIds": ["created-a"],
        "recentPrograms": [{
            "episodeId": "episode-a", "seedId": "seed-a", "title": "newest",
            "topic": None, "currentTitle": "Chapter", "updatedAt": 50,
            "progressSeconds": 20, "durationSeconds": 100,
        }],
        "savedEpisodes": [{
            "episodeId": "episode-b", "seedId": "seed-b", "title": "saved",
            "topic": None, "currentTitle": None, "updatedAt": 50,
            "progressSeconds": 0, "durationSeconds": 100, "savedAt": 50,
        }],
    }
    first = PostgresUserLibraryRepository(DATABASE_URL)
    try:
        first.merge(user_id, payload)
        first.merge(user_id, payload)
    finally:
        first.close()

    recovered = PostgresUserLibraryRepository(DATABASE_URL)
    try:
        state = recovered.snapshot(user_id)
        assert state == {
            "version": 1,
            "favoriteSeedIds": ["favorite-a"],
            "recentPrograms": payload["recentPrograms"],
            "savedEpisodes": payload["savedEpisodes"],
            "createdProgramIds": ["created-a"],
        }
    finally:
        recovered.close()
        _cleanup(user_id=user_id)


def test_quota_is_durable_across_repositories_and_same_program_is_not_double_charged() -> None:
    assert DATABASE_URL is not None
    listener_id = f"quota-test-{uuid4().hex}"
    first = PostgresGenerationQuotaRepository(DATABASE_URL)
    limits = {"guest_limit": 2, "auth_daily_limit": 10, "global_daily_limit": 100}
    try:
        reservation = first.reserve(listener_id, None, 1, **limits)
        first.charge(reservation, ["stable-program-id"])
    finally:
        first.close()

    recovered = PostgresGenerationQuotaRepository(DATABASE_URL)
    try:
        duplicate = recovered.reserve(listener_id, None, 1, **limits)
        recovered.charge(duplicate, ["stable-program-id"])
        second_program = recovered.reserve(listener_id, None, 1, **limits)
        recovered.charge(second_program, ["another-program-id"])
        with pytest.raises(QuotaExceededError, match="guest_limit"):
            recovered.reserve(listener_id, None, 1, **limits)
    finally:
        recovered.close()
        _cleanup(listener_id=listener_id)


def test_parallel_guest_reservations_cannot_exceed_the_durable_limit() -> None:
    assert DATABASE_URL is not None
    listener_id = f"quota-race-{uuid4().hex}"
    repository = PostgresGenerationQuotaRepository(DATABASE_URL)
    limits = {"guest_limit": 3, "auth_daily_limit": 10, "global_daily_limit": 100}

    def reserve_two() -> list[str]:
        return repository.reserve(listener_id, None, 2, **limits)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: _reserve_outcome(reserve_two), range(2)))
        assert sum(isinstance(item, list) for item in outcomes) == 1
        assert sum(isinstance(item, QuotaExceededError) for item in outcomes) == 1
        for item in outcomes:
            if isinstance(item, list):
                repository.release(item)
    finally:
        repository.close()
        _cleanup(listener_id=listener_id)


def test_expired_durable_pending_quota_reservation_is_reclaimed() -> None:
    assert DATABASE_URL is not None
    listener_id = f"quota-expiry-{uuid4().hex}"
    repository = PostgresGenerationQuotaRepository(DATABASE_URL)
    limits = {"guest_limit": 1, "auth_daily_limit": 10, "global_daily_limit": 100}
    try:
        abandoned = repository.reserve(listener_id, None, 1, **limits)

        async def expire_reservation() -> None:
            engine = create_async_engine(DATABASE_URL)
            async with engine.begin() as connection:
                await connection.execute(
                    update(quota_reservations)
                    .where(quota_reservations.c.id == abandoned[0])
                    .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            await engine.dispose()

        asyncio.run(expire_reservation())
        replacement = repository.reserve(listener_id, None, 1, **limits)
        assert replacement != abandoned
    finally:
        repository.close()
        _cleanup(listener_id=listener_id)


def test_episode_account_claim_survives_repository_reconstruction_and_resumes_on_device_b() -> None:
    assert DATABASE_URL is not None
    user_id = f"episode-owner-{uuid4().hex}"
    seed = EpisodeSeed(
        id=f"seed-{uuid4().hex}",
        title="Ownership",
        topic="Cross device",
        short_description="Ownership persistence test",
        estimated_duration_seconds=600,
        opening_track_ref="mock:owner-test",
        opening_track_title="Opening",
        opening_track_artist="Artist",
        cover=CoverParams(family="editorial", seed=3, palette=("#000", "#fff")),
    )
    first_repo = PostgresEpisodeRepository(DATABASE_URL)
    try:
        first_episode = EpisodeOrchestrator(first_repo).start_or_resume(
            seed, "owner-device-a", user_id
        )
        episode_id = first_episode.id
        assert first_episode.listener_id == "owner-device-a"
        assert first_repo.get(episode_id).owner_user_id == user_id
    finally:
        first_repo.close()

    recovered_repo = PostgresEpisodeRepository(DATABASE_URL)
    try:
        recovered = recovered_repo.find_by_user_seed(user_id, seed.id)
        assert recovered is not None
        assert recovered.id == episode_id
        assert recovered.listener_id == "owner-device-a"
        resumed = EpisodeOrchestrator(recovered_repo).start_or_resume(
            seed, "owner-device-b", user_id
        )
        assert resumed.id == episode_id
        assert resumed.listener_id == "owner-device-a"
    finally:
        recovered_repo.close()
        _cleanup(episode_id=episode_id)


def test_postgres_proposal_id_conflict_does_not_overwrite_owner() -> None:
    assert DATABASE_URL is not None
    proposal_id = f"conflict-test-{uuid4().hex}"
    base = ProgramProposal.from_episode_seed(EpisodeSeed(
        id="proposal-conflict-seed",
        title="Proposal",
        topic="Conflict",
        short_description="ID collision regression",
        estimated_duration_seconds=600,
        opening_track_ref="mock:conflict",
        opening_track_title="Opening",
        opening_track_artist="Artist",
        cover=CoverParams(family="editorial", seed=4, palette=("#000", "#fff")),
    )).model_copy(update={"id": proposal_id})
    repository = PostgresProgramProposalRepository(DATABASE_URL)
    try:
        repository.save_many([base], owner_listener_id="original-listener", owner_user_id="original-user")
        with pytest.raises(ProposalPersistenceConflict):
            repository.save_many(
                [base.model_copy(update={"title": "replacement"})],
                owner_listener_id="attacker-listener",
                owner_user_id="attacker-user",
            )
        assert repository.get_owner(proposal_id) == ("original-listener", "original-user")
        assert repository.get(proposal_id) == base
    finally:
        repository.close()
        _cleanup(proposal_id=proposal_id)


def _reserve_outcome(reserve) -> list[str] | QuotaExceededError:
    try:
        return reserve()
    except QuotaExceededError as error:
        return error
