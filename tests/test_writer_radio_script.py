import asyncio

from wavecast.intelligence.models import (
    ChapterPlan,
    Evidence,
    NarrativeRole,
    NoveltyDistance,
    OutputLanguage,
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


def test_writer_prompt_is_tts_aware_and_receives_budget_and_language() -> None:
    fixture = RadioWriterFixture()
    chapter = ChapterPlan(
        index=0,
        track=None,
        narrative_role=NarrativeRole.BRIDGE,
        reason="explain the scene",
        narration_goal="connect context",
    )

    asyncio.run(
        WriterService(fixture).write(
            chapter,
            [],
            target_duration_seconds=42,
            output_language=OutputLanguage.ZH_CN,
        )
    )

    # The fixture stores no prompts, so exercise the production prompt builder
    # with a tiny recorder below.
    class PromptRecorder(RadioWriterFixture):
        def __init__(self) -> None:
            self.prompt = ""

        async def structured(self, prompt: str, _output_type: type[object], **_kwargs: object) -> object:
            self.prompt = prompt
            return RadioScript.from_blocks([], intended_duration_seconds=1)

    recorder = PromptRecorder()
    asyncio.run(
        WriterService(recorder).write(
            chapter,
            [],
            target_duration_seconds=42,
            output_language=OutputLanguage.ZH_CN,
        )
    )
    assert "output language zh-CN" in recorder.prompt
    assert "Target narration duration seconds: 42" in recorder.prompt
    assert "display `3rd Coast`" in recorder.prompt
