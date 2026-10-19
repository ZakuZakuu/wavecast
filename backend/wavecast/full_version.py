"""The 完整版 of a programme: the whole episode prepared in the background.

A listener can ask for it from the player or from the tuner, and then leave. Its state is read from
the durable generation job and the episode, never kept as a separate record: the job says whether
preparation is queued, running or failed, the episode says whether it is done.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from wavecast.models import EpisodeState, LiveEpisode
from wavecast.storage.generation_jobs import (
    GenerationJob,
    GenerationJobMode,
    GenerationJobStatus,
)

#: A listener (a guest or an account) may have this many 完整版 being prepared at once.
MAX_CONCURRENT_FULL_VERSIONS = 2
#: A preparation that has not finished after this long is reported as failed, and can be retried.
FULL_VERSION_TIMEOUT_SECONDS = 20 * 60
#: Progress is estimated from finished audio, so it never claims to be done before the episode is.
_PROGRESS_CEILING = 95


class FullVersionStatus(StrEnum):
    NONE = "none"
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"


def is_active(job: GenerationJob | None) -> bool:
    """A 完整版 preparation that is queued or running (however long it has been)."""
    return (
        job is not None
        and job.mode is GenerationJobMode.FULL
        and job.status in {GenerationJobStatus.PENDING, GenerationJobStatus.RUNNING}
    )


def is_stale(job: GenerationJob, now: datetime) -> bool:
    return (now - job.requested_at).total_seconds() > FULL_VERSION_TIMEOUT_SECONDS


def full_version_status(
    episode: LiveEpisode, job: GenerationJob | None, now: datetime
) -> FullVersionStatus:
    if episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
        return FullVersionStatus.READY
    if job is None or job.mode is not GenerationJobMode.FULL:
        return FullVersionStatus.NONE
    if job.status is GenerationJobStatus.FAILED:
        return FullVersionStatus.FAILED
    if is_active(job):
        return FullVersionStatus.FAILED if is_stale(job, now) else FullVersionStatus.PREPARING
    return FullVersionStatus.NONE


def full_version_progress(episode: LiveEpisode, status: FullVersionStatus) -> int:
    """Percent of the programme's estimated length that already has audio."""
    if status is FullVersionStatus.READY:
        return 100
    if status is not FullVersionStatus.PREPARING:
        return 0
    ready = sum(
        segment.duration_seconds
        for segment in episode.timeline_segments
        if segment.is_audio_ready
    )
    return min(_PROGRESS_CEILING, max(0, round(100 * ready / episode.program_estimated_duration_seconds)))
