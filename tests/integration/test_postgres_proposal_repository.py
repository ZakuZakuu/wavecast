from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine
from wavecast.proposals import DeterministicMockProgramProposalGenerator, ProposalGenerationRequest
from wavecast.storage.proposals import (
    PostgresProgramProposalRepository,
    program_proposals_table,
)

DATABASE_URL = os.getenv("WAVECAST_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="set WAVECAST_TEST_DATABASE_URL to run Postgres integration tests"
)


def test_generated_proposal_survives_repository_reconstruction() -> None:
    assert DATABASE_URL is not None
    proposal = asyncio.run(
        DeterministicMockProgramProposalGenerator().generate(
            ProposalGenerationRequest(prompt="持久化回归测试", count=1)
        )
    )[0]
    proposal = proposal.model_copy(update={"id": f"persistence-test-{uuid4().hex}"})

    async def remove_test_row() -> None:
        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as connection:
            await connection.execute(
                delete(program_proposals_table).where(
                    program_proposals_table.c.id == proposal.id
                )
            )
        await engine.dispose()

    asyncio.run(remove_test_row())
    first = PostgresProgramProposalRepository(DATABASE_URL)
    first.save_many(
        [proposal],
        owner_listener_id="durable-listener",
        owner_user_id="durable-user",
        source="tune",
    )
    first.close()

    recovered = PostgresProgramProposalRepository(DATABASE_URL)
    try:
        assert recovered.get(proposal.id) == proposal
    finally:
        recovered.close()
        asyncio.run(remove_test_row())


def test_a_short_prefix_finds_exactly_one_proposal() -> None:
    assert DATABASE_URL is not None
    base = asyncio.run(
        DeterministicMockProgramProposalGenerator().generate(
            ProposalGenerationRequest(prompt="短链接回归测试", count=1)
        )
    )[0]
    token = uuid4().hex
    ids = [f"proposal-{token}", f"proposal-{token[:-1]}z"]
    repository = PostgresProgramProposalRepository(DATABASE_URL)
    try:
        repository.save_many([base.model_copy(update={"id": ids[0]})], owner_listener_id="short-listener")
        assert repository.find_id_by_prefix(f"proposal-{token[:12]}") == ids[0]
        # Pattern characters are data, not wildcards.
        assert repository.find_id_by_prefix("proposal-%") is None
        assert repository.find_id_by_prefix("proposal-_") is None
        repository.save_many([base.model_copy(update={"id": ids[1]})], owner_listener_id="short-listener")
        assert repository.find_id_by_prefix(f"proposal-{token[:12]}") is None
    finally:
        async def cleanup() -> None:
            engine = create_async_engine(DATABASE_URL)
            async with engine.begin() as connection:
                await connection.execute(
                    delete(program_proposals_table).where(program_proposals_table.c.id.in_(ids))
                )
            await engine.dispose()

        asyncio.run(cleanup())
        repository.close()
