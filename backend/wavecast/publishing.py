"""Published programmes: a finished programme shared as the programme itself.

The owner publishes a finished episode. Its whole audio is mixed once, checked, and then every
listener's copy points at that one fixed audio; only each listener's progress is their own. The
record says where the audio is and what the link promises, never what a listener has done.

Rules this module keeps in one place:

* what may count as published audio (a complete, checked programme feed);
* how much space the published audio may take and what a new one needs (a budget, and a reserve
  that generation can always use);
* whether a listener may still open it (revoked ones only for people who already hold a copy).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from wavecast.models.episode import CoverParams
from wavecast.stations import StationId

#: Programme ids a published programme can have are told apart from a proposal's by this prefix.
PUBLISHED_ID_PREFIX = "pub-"
#: The short link carries this many leading hex digits of the id.
SHORT_CODE_LENGTH = 10
#: One listener (a guest or an account) may keep this many programmes published at once.
MAX_PUBLISHED_PER_OWNER = 10
#: Programmes being mixed at once, in total. A mix is the heaviest thing the server does on request.
MAX_CONCURRENT_MIXES = 2
#: A publication that has not finished after this long is reported as failed and can be retried.
PUBLICATION_TIMEOUT_SECONDS = 45 * 60
#: Rough size of the audio: 192 kbit/s AAC.
AUDIO_BYTES_PER_SECOND = 192_000 // 8
#: What a mix needs on disk besides the finished audio: song sources and scratch space.
MIX_SCRATCH_BYTES = 90 * 1024 * 1024
#: Generation (narration, songs, renders) must always have this much room left.
GENERATION_RESERVE_BYTES = 150 * 1024 * 1024
#: Share of the volume the published audio may take when no explicit budget is set.
DEFAULT_BUDGET_SHARE = 0.5


class PublicationStatus(StrEnum):
    #: Waiting for the 完整版 of the episode to be made.
    PREPARING = "PREPARING"
    #: Mixing the whole programme into one fixed feed.
    MIXING = "MIXING"
    PUBLISHED = "PUBLISHED"
    #: No new copies and no listing; the audio stays for the copies that exist.
    REVOKED = "REVOKED"
    FAILED = "FAILED"


class Visibility(StrEnum):
    #: Only people who have the link.
    LINK = "LINK"
    #: Also listed on the home page.
    PUBLIC = "PUBLIC"


#: Audio of these publications must never be reclaimed: someone is making it, or someone may hold it.
PINNING_STATUSES = frozenset({
    PublicationStatus.PREPARING,
    PublicationStatus.MIXING,
    PublicationStatus.PUBLISHED,
    PublicationStatus.REVOKED,
})
#: Publications that count against an owner's limit.
LIVE_STATUSES = frozenset({
    PublicationStatus.PREPARING,
    PublicationStatus.MIXING,
    PublicationStatus.PUBLISHED,
})


class ProgrammeSnapshot(BaseModel):
    """What the link shows, taken when it was published (the owner's prompt is not part of it)."""

    title: str
    cover_title: str | None = None
    description: str
    estimated_duration_seconds: int = Field(gt=0)
    station: StationId | None = None
    route: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    opening_track_title: str
    opening_track_artist: str
    cover: CoverParams


class Publication(BaseModel):
    id: str
    code: str
    source_episode_id: str
    owner_listener_id: str
    owner_user_id: str | None = None
    status: PublicationStatus
    visibility: Visibility = Visibility.LINK
    programme: ProgrammeSnapshot
    #: Every stored object the listener's audio is made of: the manifest and its chunks.
    asset_keys: list[str] = Field(default_factory=list)
    bytes_total: int = Field(default=0, ge=0)
    #: Length of the checked audio.
    audio_seconds: float = Field(default=0, ge=0)
    plan_fingerprint: str | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def pins_audio(self) -> bool:
        return self.status in PINNING_STATUSES


def new_publication_id() -> str:
    return PUBLISHED_ID_PREFIX + uuid4().hex


def short_code(publication_id: str) -> str:
    return publication_id[len(PUBLISHED_ID_PREFIX):][:SHORT_CODE_LENGTH]


def is_publication_id(program_id: str) -> bool:
    return program_id.startswith(PUBLISHED_ID_PREFIX)


def utc_now() -> datetime:
    return datetime.now(UTC)


def estimated_audio_bytes(duration_seconds: float) -> int:
    return int(max(0.0, duration_seconds) * AUDIO_BYTES_PER_SECOND)


def published_budget_bytes(volume_total_bytes: int, configured_bytes: int | None) -> int:
    """How much the published audio may take: the configured number, else a share of the volume."""

    if configured_bytes is not None:
        return max(0, configured_bytes)
    return int(volume_total_bytes * DEFAULT_BUDGET_SHARE)


class PublishRefusal(Exception):
    """A publication that cannot start now, and the plain reason to give the owner."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def check_publish_admission(
    *,
    duration_seconds: float,
    owner_live_count: int,
    mixing_count: int,
    pinned_bytes: int,
    budget_bytes: int,
    free_bytes: int | None,
) -> None:
    """Raises PublishRefusal when a new publication must not start now.

    Three separate protections: the owner's own limit, the number of mixes running, and space (a
    budget for published audio, and a reserve that is never spent on it).
    """

    if owner_live_count >= MAX_PUBLISHED_PER_OWNER:
        raise PublishRefusal(
            "limit", f"最多同时分享 {MAX_PUBLISHED_PER_OWNER} 档。撤回一档之后，就能发布这一档。",
        )
    if mixing_count >= MAX_CONCURRENT_MIXES:
        raise PublishRefusal("busy", "现在发布的人比较多，请过一会儿再试。")
    output = estimated_audio_bytes(duration_seconds)
    if pinned_bytes + output > budget_bytes:
        raise PublishRefusal("space", "分享的空间暂时满了，过一会儿再试。")
    if free_bytes is not None and free_bytes < output + MIX_SCRATCH_BYTES + GENERATION_RESERVE_BYTES:
        raise PublishRefusal("space", "分享的空间暂时满了，过一会儿再试。")
