"""Vendor-neutral request for spoken audio: one voice's text, or an ordered dialogue.

Nothing here names a vendor.  The roles carry an opaque ``voice_id`` snapshot taken when the
request is made, so a stored request still says which voices it was rendered with after the
configuration changes (and cache keys can include it).  No adapter consumes this yet: the TTS
protocol still takes a plain string.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wavecast.models.dialogue import DialogueBlock, DialogueSpeaker


class SpeechTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: DialogueSpeaker
    text: str = Field(min_length=1)


class VoiceRoleSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: DialogueSpeaker
    voice_id: str = Field(min_length=1, max_length=200)


class SpeechRequest(BaseModel):
    """Either ``text`` (one voice, the existing path) or ``turns`` + ``roles`` (a dialogue)."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1)
    turns: list[SpeechTurn] = Field(default_factory=list)
    roles: list[VoiceRoleSnapshot] = Field(default_factory=list)
    cues: list[str] = Field(default_factory=list)
    # Vendor scales differ (MiniMax 0.9 is not Doubao 0): the number is only meaningful to the
    # adapter that the request is for.
    speed: float | None = Field(default=None, gt=0)
    audio_format: str | None = None

    @property
    def is_dialogue(self) -> bool:
        return bool(self.turns)

    @model_validator(mode="after")
    def _one_shape(self) -> "SpeechRequest":
        if (self.text is None) == (not self.turns):
            raise ValueError("a speech request is either one text or a dialogue, not both or neither")
        if self.turns:
            have = {role.speaker for role in self.roles}
            if len(have) != len(self.roles):
                raise ValueError("a speaker has more than one voice role")
            missing = {turn.speaker for turn in self.turns} - have
            if missing:
                raise ValueError(
                    "no voice role for speaker(s): " + ", ".join(sorted(s.value for s in missing))
                )
        elif self.roles:
            raise ValueError("voice roles belong to a dialogue request")
        return self

    @classmethod
    def single(
        cls, text: str, *, cues: list[str] | None = None, speed: float | None = None
    ) -> "SpeechRequest":
        return cls(text=text, cues=list(cues or []), speed=speed)

    @classmethod
    def dialogue(
        cls,
        block: DialogueBlock,
        roles: list[VoiceRoleSnapshot],
        *,
        speed: float | None = None,
        audio_format: str | None = None,
    ) -> "SpeechRequest":
        return cls(
            turns=[SpeechTurn(speaker=t.speaker, text=t.tts_text or t.text) for t in block.turns],
            roles=roles,
            speed=speed,
            audio_format=audio_format,
        )
