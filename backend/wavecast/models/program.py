from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class NarrativeRole(StrEnum):
    ANCHOR = "anchor"
    VALIDATION = "validation"
    BRIDGE = "bridge"
    CONTRAST = "contrast"
    DISCOVERY = "discovery"
    RESOLUTION = "resolution"


class ChapterPlan(BaseModel):
    id: str
    order: int = Field(ge=0)
    track_ref: str
    narrative_role: NarrativeRole
    reason: str
    target_narration_seconds: int = Field(ge=0)


class ProgramSkeleton(BaseModel):
    id: str
    episode_id: str
    thesis: str
    chapters: list[ChapterPlan]
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
