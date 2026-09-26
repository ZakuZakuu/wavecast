"""Postgres persistence for generated editorial program proposals."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy import Column, DateTime, Index, String, Table, desc, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from wavecast.deployment import normalize_database_url
from wavecast.proposals import ProgramProposal, ProposalPersistenceConflict
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

    def get_owner(self, proposal_id: str) -> tuple[str | None, str | None] | None:
        return cast(tuple[str | None, str | None] | None, self._run(self._get_owner(proposal_id)))

    def claim_user(self, proposal_id: str, listener_id: str, user_id: str) -> bool:
        return bool(self._run(self._claim_user(proposal_id, listener_id, user_id)))

    def get_for_user(self, user_id: str, proposal_id: str) -> ProgramProposal | None:
        return cast(ProgramProposal | None, self._run(self._get_for_user(user_id, proposal_id)))

    def list_for_user(self, user_id: str, *, limit: int = 20) -> list[ProgramProposal]:
        return cast(list[ProgramProposal], self._run(self._list_for_user(user_id, limit)))

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
        statement = statement.on_conflict_do_nothing(
            index_elements=[program_proposals_table.c.id]
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)
            existing = (
                await connection.execute(
                    select(
                        program_proposals_table.c.id,
                        program_proposals_table.c.owner_listener_id,
                        program_proposals_table.c.owner_user_id,
                        program_proposals_table.c.source,
                        program_proposals_table.c.payload,
                    ).where(program_proposals_table.c.id.in_([row["id"] for row in rows]))
                )
            ).all()
            expected = {row["id"]: row for row in rows}
            if len(existing) != len(rows) or any(
                row.owner_listener_id != owner_listener_id
                or row.owner_user_id != owner_user_id
                or row.source != source
                or dict(row.payload) != expected[row.id]["payload"]
                for row in existing
            ):
                raise ProposalPersistenceConflict("proposal id already exists")

    async def _get(self, proposal_id: str) -> ProgramProposal | None:
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(program_proposals_table.c.payload).where(program_proposals_table.c.id == proposal_id))).first()
        return ProgramProposal.model_validate(row.payload) if row else None

    async def _get_owner(self, proposal_id: str) -> tuple[str | None, str | None] | None:
        async with self.engine.connect() as connection:
            row = (await connection.execute(select(program_proposals_table.c.owner_listener_id, program_proposals_table.c.owner_user_id).where(program_proposals_table.c.id == proposal_id))).first()
        return (row.owner_listener_id, row.owner_user_id) if row else None

    async def _claim_user(self, proposal_id: str, listener_id: str, user_id: str) -> bool:
        async with self.engine.begin() as connection:
            result = await connection.execute(
                update(program_proposals_table)
                .where(
                    program_proposals_table.c.id == proposal_id,
                    program_proposals_table.c.owner_listener_id == listener_id,
                    (program_proposals_table.c.owner_user_id.is_(None))
                    | (program_proposals_table.c.owner_user_id == user_id),
                )
                .values(owner_user_id=user_id)
            )
        return result.rowcount == 1

    async def _get_for_user(self, user_id: str, proposal_id: str) -> ProgramProposal | None:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(program_proposals_table.c.payload).where(
                        program_proposals_table.c.id == proposal_id,
                        program_proposals_table.c.owner_user_id == user_id,
                    )
                )
            ).first()
        return ProgramProposal.model_validate(row.payload) if row else None

    async def _list_for_user(self, user_id: str, limit: int) -> list[ProgramProposal]:
        async with self.engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(program_proposals_table.c.payload)
                    .where(program_proposals_table.c.owner_user_id == user_id)
                    .order_by(desc(program_proposals_table.c.created_at))
                    .limit(limit)
                )
            ).all()
        return [ProgramProposal.model_validate(row.payload) for row in rows]
