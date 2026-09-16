import asyncio

from wavecast.intelligence.models import (
    ChapterPlan,
    Evidence,
    NarrativeRole,
    NoveltyDistance,
    RadioScript,
    RadioScriptBlockKind,
    TrackProposal,
)
from wavecast.intelligence.writer import WriterService


class RadioWriterFixture:
    async def structured(self, _prompt: str, _output_type: type[object], **_kwargs: object) -> object:
        return RadioScript.from_blocks(
            [
                (RadioScriptBlockKind.INTRO, "Welcome.", 5),
                (RadioScriptBlockKind.TRACK_INTRO, "Listen for the bass.", 6),
                (RadioScriptBlockKind.OUTRO, "Until next time.", 5),
            ],
            intended_duration_seconds=16,
        )


def test_writer_returns_structured_radio_script_blocks() -> None:
    chapter = ChapterPlan(
        index=0,
        track=TrackProposal(artist="Artist", title="Track", confidence=0.8),
        narrative_role=NarrativeRole.ANCHOR,
        reason="anchor",
        novelty_distance=NoveltyDistance.CLOSE,
        narration_goal="introduce",
    )

    result = asyncio.run(
        WriterService(RadioWriterFixture()).write(
            chapter,
            [Evidence(id="e1", claim_or_excerpt="fact", source_url="https://example.test", source_provider="fixture", confidence=0.8, query="q")],
        )
    )

    assert isinstance(result, RadioScript)
    assert [block.kind for block in result.blocks] == [
        RadioScriptBlockKind.INTRO,
        RadioScriptBlockKind.TRACK_INTRO,
        RadioScriptBlockKind.OUTRO,
    ]
