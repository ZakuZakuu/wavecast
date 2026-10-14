"""Application-side checks of a dialogue block.

A structurally valid block is not a supported one.  This checks what the schema cannot: that the
facts a turn cites exist in the material the caller supplied, and that a block whose purpose is
researched talk actually cites some.  Whether the cited facts support what is *said* is the fact
checker's job (a later batch); nothing here fills a missing reference in to make a block pass.
"""

from collections.abc import Collection

from wavecast.models.dialogue import (
    PURPOSES_REQUIRING_FACTS,
    DialogueBlock,
    DialogueDraft,
    DialoguePurpose,
)


class DialogueValidationError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def validate_dialogue_block(
    block: DialogueBlock,
    *,
    allowed_fact_refs: Collection[str],
    expected_slot_id: str | None = None,
    allow_tts_text: bool = False,
) -> DialogueBlock:
    """Return ``block`` unchanged if it is consistent with the caller's context, else raise.

    A turn's ``tts_text`` is what would be *spoken*, and the fact check reads only ``text``.  So
    a block that carries one is refused unless the caller says it came from a deterministic
    conversion of the checked text (``allow_tts_text=True``); a model never supplies it.
    """

    allowed = set(allowed_fact_refs)
    problems: list[str] = []
    if expected_slot_id is not None and block.slot_id != expected_slot_id:
        problems.append(f"slot_id {block.slot_id!r} is not the expected slot {expected_slot_id!r}")
    for index, turn in enumerate(block.turns):
        unknown = [ref for ref in turn.fact_refs if ref not in allowed]
        if unknown:
            problems.append(f"turn {index} cites unknown fact_refs: {', '.join(unknown[:5])}")
    if not allow_tts_text:
        for index, turn in enumerate(block.turns):
            if turn.tts_text is not None:
                problems.append(f"turn {index} carries tts_text that was never fact-checked")
    if block.purpose in PURPOSES_REQUIRING_FACTS and not block.fact_refs:
        problems.append(f"a {block.purpose.value} block must cite at least one fact_ref")
    if problems:
        raise DialogueValidationError(problems)
    return block


def block_from_draft(
    draft: DialogueDraft,
    *,
    block_id: str,
    slot_id: str,
    purpose: DialoguePurpose,
    duration_seconds: int,
    allowed_fact_refs: Collection[str],
    story_id: str | None = None,
) -> DialogueBlock:
    block = DialogueBlock.from_draft(
        draft,
        block_id=block_id,
        slot_id=slot_id,
        purpose=purpose,
        duration_seconds=duration_seconds,
        story_id=story_id,
    )
    return validate_dialogue_block(block, allowed_fact_refs=allowed_fact_refs, expected_slot_id=slot_id)
