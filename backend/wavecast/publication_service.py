"""Publishing a finished episode: waiting for its 完整版, mixing it once, checking it, going live.

Everything provider- and web-specific is passed in, so the rules (when it may start, what counts as
a good mix, what a failure leaves behind) can be tested without a server or a renderer.

The record in the repository is the only state. A mix runs as a task of this process; when the
process restarts the record still says MIXING, and the next look at it starts the mix again.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from wavecast.full_version import FullVersionStatus
from wavecast.models.episode import LiveEpisode
from wavecast.providers.contracts import ObjectStorageProvider
from wavecast.publishing import (
    GENERATION_RESERVE_BYTES,
    LIVE_STATUSES,
    PUBLICATION_TIMEOUT_SECONDS,
    ProgrammeSnapshot,
    Publication,
    PublicationStatus,
    PublishRefusal,
    Visibility,
    check_publish_admission,
    new_publication_id,
    short_code,
    utc_now,
)
from wavecast.rendering.programme import ProgramRenderManifest, manifest_key
from wavecast.storage.publications import PublicationConflictError, PublicationRepository

logger = logging.getLogger(__name__)

#: A mix is made in steps this long, so that how far it has got is real, and a step can be retried.
MIX_STEP_SECONDS = 900.0


class MixFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PublicationService:
    def __init__(
        self,
        *,
        repository: PublicationRepository,
        episode: Callable[[str], LiveEpisode],
        mark_published: Callable[[str], None],
        render: Callable[[str, float], Awaitable[ProgramRenderManifest]],
        plan_info: Callable[[str], tuple[float, str]],
        full_state: Callable[[LiveEpisode], FullVersionStatus],
        storage: ObjectStorageProvider,
        free_bytes: Callable[[], int | None],
        budget_bytes: Callable[[], int],
        snapshot_for: Callable[[LiveEpisode], ProgrammeSnapshot | None],
        taken_down: Callable[[str], bool] = lambda _id: False,
        now: Callable[[], datetime] = utc_now,
        step_seconds: float = MIX_STEP_SECONDS,
    ) -> None:
        self.repository = repository
        self._episode = episode
        self._mark_published = mark_published
        self._render = render
        self._plan_info = plan_info
        self._full_state = full_state
        self._storage = storage
        self._free_bytes = free_bytes
        self._budget_bytes = budget_bytes
        self._snapshot_for = snapshot_for
        self._taken_down = taken_down
        self._now = now
        self._step_seconds = step_seconds
        self._running: dict[str, asyncio.Task[None] | None] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- publishing ----------------------------------------------------------------------------

    def is_taken_down(self, publication_id: str) -> bool:
        return self._taken_down(publication_id)

    def _admit(self, episode: LiveEpisode, owner_listener: str, owner_user: str | None) -> None:
        check_publish_admission(
            duration_seconds=episode.program_estimated_duration_seconds,
            owner_live_count=self.repository.count_for_owner(owner_listener, owner_user, LIVE_STATUSES),
            mixing_count=self.repository.count_status({PublicationStatus.MIXING}),
            pinned_bytes=self.repository.pinned_bytes(),
            budget_bytes=self._budget_bytes(),
            free_bytes=self._free_bytes(),
        )

    def publish(
        self,
        episode_id: str,
        *,
        owner_listener_id: str,
        owner_user_id: str | None,
        visibility: Visibility,
    ) -> Publication:
        """Starts (or carries on, or brings back) the publication of an episode the caller owns.

        The caller has already queued the episode's 完整版 when it is not whole yet. Raises
        PublishRefusal when the publication cannot start now.
        """

        existing = self.repository.get_for_episode(episode_id)
        if existing is not None and self.is_taken_down(existing.id):
            raise PublishRefusal("blocked", "这档节目不能分享。")
        episode = self._episode(episode_id)
        if existing is None:
            snapshot = self._snapshot_for(episode)
            if snapshot is None:
                raise PublishRefusal("unavailable", "这档节目现在没法分享。")
            self._admit(episode, owner_listener_id, owner_user_id)
            identifier = new_publication_id()
            now = self._now()
            try:
                created = self.repository.create(Publication(
                    id=identifier, code=short_code(identifier), source_episode_id=episode_id,
                    owner_listener_id=owner_listener_id, owner_user_id=owner_user_id,
                    status=PublicationStatus.PREPARING, visibility=visibility,
                    programme=snapshot, created_at=now, updated_at=now,
                ))
            except PublicationConflictError:
                return self.publish(
                    episode_id, owner_listener_id=owner_listener_id,
                    owner_user_id=owner_user_id, visibility=visibility,
                )
            return self.advance(created.id) or created

        if existing.status is PublicationStatus.PUBLISHED:
            if existing.visibility is not visibility:
                return self.repository.update(existing.id, visibility=visibility) or existing
            return existing
        if existing.status is PublicationStatus.REVOKED:
            if existing.published_at is None:
                raise PublishRefusal("unavailable", "这档节目现在没法分享。")
            check_publish_admission(
                duration_seconds=1,
                owner_live_count=self.repository.count_for_owner(owner_listener_id, owner_user_id, LIVE_STATUSES),
                mixing_count=0, pinned_bytes=0, budget_bytes=1, free_bytes=None,
            )
            return self.repository.update(
                existing.id, only_from={PublicationStatus.REVOKED},
                status=PublicationStatus.PUBLISHED, visibility=visibility, revoked_at=None,
            ) or existing
        if existing.status is PublicationStatus.FAILED:
            self._admit(episode, owner_listener_id, owner_user_id)
            restarted = self.repository.update(
                existing.id, only_from={PublicationStatus.FAILED},
                status=PublicationStatus.PREPARING, visibility=visibility, error_code=None,
                audio_seconds=0,
            )
            return (self.advance(existing.id) if restarted else None) or restarted or existing
        # Being made already: only the choice of who may listen can change.
        if existing.visibility is not visibility:
            existing = self.repository.update(existing.id, visibility=visibility) or existing
        return self.advance(existing.id) or existing

    def revoke(self, publication_id: str) -> Publication | None:
        """No new copies and no listing. One still being made is stopped; its audio is not kept."""

        current = self.repository.get(publication_id)
        if current is None:
            return None
        if current.status is PublicationStatus.PUBLISHED:
            return self.repository.update(
                publication_id, only_from={PublicationStatus.PUBLISHED},
                status=PublicationStatus.REVOKED, revoked_at=self._now(),
            ) or current
        if current.status in {PublicationStatus.PREPARING, PublicationStatus.MIXING}:
            return self.repository.update(
                publication_id, only_from={PublicationStatus.PREPARING, PublicationStatus.MIXING},
                status=PublicationStatus.FAILED, error_code="cancelled",
            ) or current
        return current

    def restore(self, publication_id: str, owner_listener_id: str, owner_user_id: str | None) -> Publication | None:
        """Undo a revoke."""

        current = self.repository.get(publication_id)
        if current is None or current.status is not PublicationStatus.REVOKED or current.published_at is None:
            return current
        if self.is_taken_down(publication_id):
            return current
        return self.repository.update(
            publication_id, only_from={PublicationStatus.REVOKED},
            status=PublicationStatus.PUBLISHED, revoked_at=None,
        ) or current

    def set_visibility(self, publication_id: str, visibility: Visibility) -> Publication | None:
        current = self.repository.get(publication_id)
        if current is None or current.status is PublicationStatus.REVOKED:
            return current
        return self.repository.update(publication_id, visibility=visibility) or current

    # -- moving along --------------------------------------------------------------------------

    def advance(self, publication_id: str) -> Publication | None:
        """Takes the next step when one is due. Called whenever someone looks, and when an episode's
        完整版 is done, so nothing depends on a page staying open."""

        current = self.repository.get(publication_id)
        if current is None or current.status not in {PublicationStatus.PREPARING, PublicationStatus.MIXING}:
            return current
        if (self._now() - current.updated_at).total_seconds() > PUBLICATION_TIMEOUT_SECONDS:
            return self._fail(current, "timeout")
        if self.is_taken_down(current.id):
            return self._fail(current, "cancelled")
        if current.status is PublicationStatus.PREPARING:
            state = self._full_state(self._episode(current.source_episode_id))
            if state is FullVersionStatus.FAILED or state is FullVersionStatus.NONE:
                return self._fail(current, "full_version_failed")
            if state is FullVersionStatus.READY:
                moved = self.repository.update(
                    current.id, only_from={PublicationStatus.PREPARING},
                    status=PublicationStatus.MIXING, audio_seconds=0,
                )
                if moved is not None:
                    self._start_mix(current.id)
                    return moved
            return self.repository.get(current.id)
        if current.id not in self._running:
            self._start_mix(current.id)
        return current

    def _fail(self, current: Publication, code: str) -> Publication | None:
        return self.repository.update(
            current.id, only_from={PublicationStatus.PREPARING, PublicationStatus.MIXING},
            status=PublicationStatus.FAILED, error_code=code,
        ) or self.repository.get(current.id)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """The loop mixes run on. Steps are taken from worker threads too, so it is remembered."""

        self._loop = loop

    def _start_mix(self, publication_id: str) -> None:
        if publication_id in self._running:
            return
        loop: asyncio.AbstractEventLoop | None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
        if loop is None:
            logger.warning("publication_mix_has_no_loop publication_id=%s", publication_id)
            return
        self._running[publication_id] = None
        loop.call_soon_threadsafe(self._create_task, loop, publication_id)

    def _create_task(self, loop: asyncio.AbstractEventLoop, publication_id: str) -> None:
        task = loop.create_task(self._mix(publication_id))
        self._running[publication_id] = task
        task.add_done_callback(lambda _done: self._running.pop(publication_id, None))

    async def wait_idle(self) -> None:
        """Waits for the mixes now running (for tests and an orderly shutdown)."""

        while True:
            scheduled = list(self._running.values())
            tasks = [task for task in scheduled if task is not None and not task.done()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            elif not any(task is None for task in scheduled):
                return
            # Let the finished tasks' callbacks run before looking again.
            await asyncio.sleep(0)

    # -- the mix -------------------------------------------------------------------------------

    async def _mix(self, publication_id: str) -> None:
        try:
            current = self.repository.get(publication_id)
            if current is None or current.status is not PublicationStatus.MIXING:
                return
            episode_id = current.source_episode_id
            reached = -1.0
            manifest: ProgramRenderManifest | None = None
            while True:
                free = self._free_bytes()
                if free is not None and free < GENERATION_RESERVE_BYTES:
                    raise MixFailure("space")
                manifest = await self._render(episode_id, self._step_seconds)
                if self.repository.get(publication_id) is None:
                    return
                self.repository.update(
                    publication_id, only_from={PublicationStatus.MIXING},
                    audio_seconds=manifest.rendered_frontier_seconds,
                )
                if manifest.complete:
                    break
                if manifest.rendered_frontier_seconds <= reached:
                    raise MixFailure("no_progress")
                reached = manifest.rendered_frontier_seconds
            keys, total = await self._verify(episode_id, manifest)
            _seconds, fingerprint = self._plan_info(episode_id)
            published = self.repository.update(
                publication_id, only_from={PublicationStatus.MIXING},
                status=PublicationStatus.PUBLISHED, asset_keys=keys, bytes_total=total,
                audio_seconds=manifest.rendered_frontier_seconds, plan_fingerprint=fingerprint,
                error_code=None, published_at=self._now(), revoked_at=None,
            )
            if published is not None:
                self._mark_published(episode_id)
                logger.info(
                    "publication_published publication_id=%s episode_id=%s bytes=%s seconds=%.1f",
                    publication_id, episode_id, total, manifest.rendered_frontier_seconds,
                )
        except MixFailure as failure:
            logger.warning("publication_mix_failed publication_id=%s code=%s", publication_id, failure.code)
            self.repository.update(
                publication_id, only_from={PublicationStatus.MIXING},
                status=PublicationStatus.FAILED, error_code=failure.code,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the owner is told it did not work; the log has the rest
            logger.exception("publication_mix_failed publication_id=%s", publication_id)
            self.repository.update(
                publication_id, only_from={PublicationStatus.MIXING},
                status=PublicationStatus.FAILED, error_code=_error_code(error),
            )

    async def _verify(self, episode_id: str, manifest: ProgramRenderManifest) -> tuple[list[str], int]:
        """The audio is whole and unchanged: every chunk is stored and matches the hash it was
        published with, and the feed runs as long as the programme does."""

        if not manifest.complete or not manifest.chunks:
            raise MixFailure("incomplete")
        plan_seconds, _fingerprint = self._plan_info(episode_id)
        if manifest.rendered_frontier_seconds + 0.5 < plan_seconds:
            raise MixFailure("short_audio")
        keys = [manifest_key(episode_id)]
        total = 0
        for chunk in manifest.chunks:
            stored = await self._storage.get(chunk.asset_key)
            if stored is None or not stored.content:
                raise MixFailure("missing_audio")
            if hashlib.sha256(stored.content).hexdigest() != chunk.content_sha256:
                raise MixFailure("audio_changed")
            keys.append(chunk.asset_key)
            total += len(stored.content)
        return keys, total


def _error_code(error: Exception) -> str:
    status = getattr(error, "status_code", None)
    return f"mix_http_{status}" if isinstance(status, int) else "mix_failed"
