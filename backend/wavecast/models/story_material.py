"""Bounded shared story material: facts the hosts may rely on, each tied to its source text.

The material is what a researched passage stands on, not what is said.  It holds checkable
facts (each bound to one ``Evidence`` and a verbatim supporting quote), the object and version
each fact is about, the editorial angle (marked as a judgement, never as a fact), what must
not be inferred, and housekeeping that is never spoken.  It carries no lines: the Writer picks
the telling and the turn-taking.

``fact_id`` and ``Evidence.id`` are separate namespaces on purpose.  A dialogue turn cites fact
ids (what the turn *used*); the fact maps to the evidence that supports it.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_MATERIAL_FACTS = 12
MIN_FACT_QUOTE_CHARS = 4


class StoryScope(StrEnum):
    """What a fact is about: this recording, its album/release, or the person and period."""

    RECORDING = "recording"
    ALBUM = "album"
    BACKGROUND = "background"


class MaterialFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(min_length=1, max_length=60)
    statement: str = Field(min_length=1, max_length=400)
    evidence_id: str = Field(min_length=1, max_length=120)
    # A stretch of the evidence text, copied verbatim; code checks it against the evidence.
    quote: str = Field(min_length=MIN_FACT_QUOTE_CHARS, max_length=300)
    scope: StoryScope
    # Whom or what the statement is about, and (for a recording) which recording or release it
    # holds for.  ``None`` means it is not tied to one version.
    subject: str = Field(min_length=1, max_length=120)
    version_scope: str | None = Field(default=None, min_length=1, max_length=200)


class StoryMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=120)
    scope: StoryScope
    recording_refs: list[str] = Field(default_factory=list, max_length=4)
    central_question: str = Field(min_length=1, max_length=200)
    facts: list[MaterialFact] = Field(min_length=1, max_length=MAX_MATERIAL_FACTS)
    # Why this suits the programme: a judgement of the editor, not a fact; hosts may frame it
    # as "one way to listen", never as something a source says.
    editorial_angle: str | None = Field(default=None, min_length=1, max_length=300)
    do_not_infer: list[str] = Field(default_factory=list, max_length=6)
    # Housekeeping (catalogue numbers, source notes): kept for inspection, never spoken.
    backstage: list[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _unique_fact_ids(self) -> "StoryMaterial":
        ids = [fact.fact_id for fact in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("fact_id values must be unique within a story")
        return self

    @property
    def fact_ids(self) -> list[str]:
        return [fact.fact_id for fact in self.facts]

    def fact(self, fact_id: str) -> MaterialFact | None:
        return next((fact for fact in self.facts if fact.fact_id == fact_id), None)
