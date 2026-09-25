"""Postgres persistence for generated editorial program proposals."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy import Column, DateTime, Index, String, Table, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.proposals import ProgramProposal
from wavecast.storage.schema import metadata

program_proposals_table = Table(
    "program_proposals",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("owner_listener_id", String(128), nullable=True),
    Column("owner_user_id", String(128), nullable=True),
    Column("source", String(32), nullable=False, default="tune"),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_program_proposals_owner_listener_id", program_proposals_table.c.owner_listener_id)
Index("ix_program_proposals_owner_user_id", program_proposals_table.c.owner_user_id)
Index("ix_program_proposals_created_at", program_proposals_table.c.created_at)


class PostgresProgramProposalRepository:
    """Durable proposal repository using the same sync boundary as episodes."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            normalize_database_url(database_url), poolclass=NullPool
        )

    def save_many(
        self,
        proposals: Iterable[ProgramProposal],
        *,
        owner_listener_id: str | None = None,
        owner_user_id: str | None = None,
        source: str = "tune",
    ) -> None:
        self._run(
            self._save_many(
                list(proposals), owner_listener_id=owner_listener_id,
                owner_user_id=owner_user_id, source=source,
            )
        )

    def get(self, proposal_id: str) -> ProgramProposal | None:
        return cast(ProgramProposal | None, self._run(self._get(proposal_id)))

    def close(self) -> None:
        self._run(self.engine.dispose())

    @staticmethod
    def _run(coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    async def _save_many(
        self,
        proposals: list[ProgramProposal],
        *,
        owner_listener_id: str | None,
        owner_user_id: str | None,
        source: str,
    ) -> None:
        if not proposals:
            return
        rows = [
            {
                "id": proposal.id,
                "owner_listener_id": owner_listener_id,
                "owner_user_id": owner_user_id,
                "source": source,
                "payload": proposal.model_dump(mode="json"),
                "created_at": proposal.created_at,
            }
            for proposal in proposals
        ]
        statement = insert(program_proposals_table).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=[program_proposals_table.c.id],
            set_={
                "owner_listener_id": statement.excluded.owner_listener_id,
                "owner_user_id": statement.excluded.owner_user_id,
                "source": statement.excluded.source,
                "payload": statement.excluded.payload,
                "created_at": statement.excluded.created_at,
            },
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def _get(self, proposal_id: str) -> ProgramProposal | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(program_proposals_table.c.payload).where(
                        program_proposals_table.c.id == proposal_id
                    )
                )
            ).first()
        return ProgramProposal.model_validate(row.payload) if row else None
