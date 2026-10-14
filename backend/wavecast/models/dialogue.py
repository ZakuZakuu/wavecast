"""Vendor-neutral two-host dialogue: what is said, by which logical host, on what facts.

A dialogue block is the *source* of a spoken passage.  The single text a one-voice path needs
is derived from its turns, never stored beside them, so the two cannot drift apart.  Logical
speakers (``A``/``B``) are not voices: which vendor voice speaks which role is a separate,
per-request snapshot (``wavecast.providers.speech``).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

MAX_DIALOGUE_TURNS = 20
MAX_TURN_CHARS = 1500


class DialogueSpeaker(StrEnum):
    """Logical host.  A speaks first; neither letter names a voice."""

    A = "A"
    B = "B"


class DialoguePurpose(StrEnum):
    """What a block is for.  Only some purposes must stand on researched facts."""

    OPENING = "opening"
    TRANSITION = "transition"
    STORY = "story"
    OUTRO = "outro"


# A story block is researched talk and must cite its facts; an opening, a hand-over or a
# sign-off may legitimately cite nothing.
PURPOSES_REQUIRING_FACTS = frozenset({DialoguePurpose.STORY})


class DialogueNotSupportedError(ValueError):
    """A path that cannot carry a dialogue was handed one.

    Raised instead of quietly flattening the block to text and going on: the turns, the speakers
    and the fact references would be lost without anyone noticing.
    """


class DialogueTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: DialogueSpeaker
    text: str = Field(min_length=1, max_length=MAX_TURN_CHARS)
    # Pronunciation-aware rendering of ``text`` for the voice; absent means "say ``text``".
    tts_text: str | None = Field(default=None, min_length=1, max_length=MAX_TURN_CHARS)
    # The material facts this turn relies on.  Required, and empty is allowed (a hand-over, a
    # question with no factual premise); a turn that states or presumes a fact must list it.
    fact_refs: list[str]


class DraftTurn(BaseModel):
    """One turn as a model writes it.

    There is deliberately no ``tts_text``: what is *spoken* has to be what was fact-checked, and
    only ``text`` is.  A pronunciation rendering will come from a deterministic conversion of the
    checked text (a later batch), never from the Writer.
    """

    model_config = ConfigDict(extra="forbid")

    speaker: DialogueSpeaker
    text: str = Field(min_length=1, max_length=MAX_TURN_CHARS)
    fact_refs: list[str]


class DialogueDraft(BaseModel):
    """What a model returns: turns only.  Identity and timing are the application's."""

    model_config = ConfigDict(extra="forbid")

    turns: list[DraftTurn] = Field(min_length=1, max_length=MAX_DIALOGUE_TURNS)


class VoiceRoleSnapshot(BaseModel):
    """Which voice spoke which logical host, taken when audio was requested.

    ``voice_id`` is opaque here: it names a voice in whatever vendor the audio came from.  The
    dialogue itself never contains one.
    """

    model_config = ConfigDict(extra="forbid")

    speaker: DialogueSpeaker
    voice_id: str = Field(min_length=1, max_length=200)


class DialogueBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1, max_length=120)
    slot_id: str = Field(min_length=1, max_length=120)
    # The story the passage tells (``StoryMaterial.story_id``), so that using a story can be
    # tracked and a story is not told twice.  Absent only on blocks that tell no shared story.
    story_id: str | None = Field(default=None, min_length=1, max_length=80)
    purpose: DialoguePurpose
    turns: list[DialogueTurn] = Field(min_length=1, max_length=MAX_DIALOGUE_TURNS)
    duration_seconds: int = Field(ge=1, le=300)

    @classmethod
    def from_draft(
        cls,
        draft: DialogueDraft,
        *,
        block_id: str,
        slot_id: str,
        purpose: DialoguePurpose,
        duration_seconds: int,
        story_id: str | None = None,
    ) -> "DialogueBlock":
        return cls(
            block_id=block_id,
            slot_id=slot_id,
            story_id=story_id,
            purpose=purpose,
            turns=[
                DialogueTurn(speaker=turn.speaker, text=turn.text, tts_text=None, fact_refs=turn.fact_refs)
                for turn in draft.turns
            ],
            duration_seconds=duration_seconds,
        )

    @property
    def text(self) -> str:
        """Visible copy for one-voice callers: the turns in order, without speaker labels."""
        return "\n".join(turn.text for turn in self.turns)

    @property
    def tts_text(self) -> str | None:
        """Spoken copy for one voice, or ``None`` when no turn needs its own rendering."""
        if all(turn.tts_text is None for turn in self.turns):
            return None
        return "\n".join(turn.tts_text or turn.text for turn in self.turns)

    @property
    def fact_refs(self) -> list[str]:
        seen: dict[str, None] = {}
        for turn in self.turns:
            for ref in turn.fact_refs:
                seen.setdefault(ref)
        return list(seen)


class DialogueIssue(BaseModel):
    """One problem the fact check found in a turn (kept with the saved passage for inspection)."""

    model_config = ConfigDict(extra="forbid")

    turn: int = Field(ge=0)
    sentence: int = Field(ge=0)
    code: str = Field(min_length=1, max_length=60)
    message: str = Field(min_length=1, max_length=600)
