from pydantic import BaseModel, ConfigDict, Field


class MixdownArtifact(BaseModel):
    """A published MP3 produced from one canonical MixPlan."""

    model_config = ConfigDict(frozen=True)

    episode_id: str = Field(min_length=1, serialization_alias="episodeId")
    plan_fingerprint: str = Field(min_length=1, serialization_alias="planFingerprint")
    audio_url: str = Field(min_length=1, serialization_alias="audioUrl")
    content_type: str = Field(default="audio/mpeg", serialization_alias="contentType")
    duration_seconds: float = Field(gt=0, serialization_alias="durationSeconds")
