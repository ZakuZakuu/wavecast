import asyncio

from wavecast.intelligence.models import (
    ChapterPlan,
    Evidence,
    NarrationSlotContext,
    NarrativeRole,
    NoveltyDistance,
    OutputLanguage,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
    TrackProposal,
)
from wavecast.intelligence.writer import WriterService
from wavecast.providers.profiles import InferenceProfile, StructuredTransport


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
    assert "at most one block for each provided slot" in recorder.prompt
    assert "soft pacing guide, not a quota" in recorder.prompt
    assert "do not add extra blocks just to fill the target duration" in recorder.prompt
    assert "must return exactly one `outro` block" in recorder.prompt


def test_writer_radio_guidance_is_scoped_to_zh_cn() -> None:
    class PromptRecorder(RadioWriterFixture):
        def __init__(self) -> None:
            self.prompt = ""

        async def structured(self, prompt: str, _output_type: type[object], **_kwargs: object) -> object:
            self.prompt = prompt
            return RadioScript.from_blocks([], intended_duration_seconds=1)

    chapter = ChapterPlan(
        index=0,
        track=None,
        narrative_role=NarrativeRole.BRIDGE,
        reason="connect context",
        narration_goal="connect",
    )

    zh = PromptRecorder()
    asyncio.run(WriterService(zh).write(chapter, [], output_language=OutputLanguage.ZH_CN))
    assert "先说具体可听的声音" in zh.prompt
    assert "证据不足时宁可简单准确" in zh.prompt
    assert "LIGHT host mode" in zh.prompt
    assert "8-18 seconds" in zh.prompt
    assert "已经听过的中间 artist/track/listen-for detail" in zh.prompt
    assert "OUTRO 回扣本期 thesis" in zh.prompt

    for language in (OutputLanguage.EN_US, OutputLanguage.JA_JP):
        recorder = PromptRecorder()
        asyncio.run(WriterService(recorder).write(chapter, [], output_language=language))
        assert "先说具体可听的声音" not in recorder.prompt
        assert "OUTRO 回扣本期 thesis" not in recorder.prompt


def test_writer_uses_synthesis_profile() -> None:
    class ProfileRecorder(RadioWriterFixture):
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        async def structured(self, _prompt: str, _output_type: type[object], **kwargs: object) -> object:
            self.kwargs = kwargs
            return RadioScript.from_blocks([], intended_duration_seconds=1)

    recorder = ProfileRecorder()
    chapter = ChapterPlan(
        index=0,
        track=None,
        narrative_role=NarrativeRole.BRIDGE,
        reason="synthesis",
        narration_goal="connect",
    )

    asyncio.run(WriterService(recorder).write(chapter, []))

    assert recorder.kwargs["transport"] is StructuredTransport.RESPONSES_JSON_SCHEMA
    assert recorder.kwargs["profile"] is InferenceProfile.SYNTHESIS
    assert recorder.kwargs["stage"] == "writer"


def test_writer_allows_fast_profile_for_latency_sensitive_first_bridge() -> None:
    class ProfileRecorder(RadioWriterFixture):
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        async def structured(
            self,
            _prompt: str,
            _output_type: type[object],
            **kwargs: object,
        ) -> object:
            self.kwargs = kwargs
            return RadioScript.from_blocks([], intended_duration_seconds=1)

    recorder = ProfileRecorder()
    chapter = ChapterPlan(
        index=1,
        track=None,
        narrative_role=NarrativeRole.BRIDGE,
        reason="fast bridge",
        narration_goal="connect",
    )

    asyncio.run(
        WriterService(recorder).write(
            chapter,
            [],
            inference_profile=InferenceProfile.FAST,
        )
    )

    assert recorder.kwargs["profile"] is InferenceProfile.FAST
    assert recorder.kwargs["stage"] == "writer"


def test_writer_receives_resolved_slot_context_and_strips_numeric_placement() -> None:
    class PlacementFixture:
        def __init__(self) -> None:
            self.prompt = ""

        async def structured(self, prompt: str, _output_type: type[object], **_kwargs: object) -> object:
            self.prompt = prompt
            return RadioScript(
                blocks=[
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.TRANSITION,
                        text="slot-aware narration",
                        duration_seconds=4,
                        track_index=99,
                    )
                ]
            )

    fixture = PlacementFixture()
    chapter = ChapterPlan(
        index=2,
        track=None,
        narrative_role=NarrativeRole.BRIDGE,
        reason="unresolved narrative beat",
        narration_goal="connect the two playable songs",
    )
    context = NarrationSlotContext(
        chapter_index=2,
        chapter_track=None,
        just_played_track=ResolvedTrack(
            track_ref="mock:second",
            canonical_artist="Second Artist",
            canonical_title="Second Song",
        ),
        upcoming_track=ResolvedTrack(
            track_ref="mock:third",
            canonical_artist="Third Artist",
            canonical_title="Third Song",
        ),
    )

    result = asyncio.run(
        WriterService(fixture).write(chapter, [], slot_context=context)
    )

    assert result.blocks[0].track_index is None  # type: ignore[union-attr]
    assert '"chapter_index": 2' in fixture.prompt
    assert '"canonical_title": "Second Song"' in fixture.prompt
    assert '"canonical_title": "Third Song"' in fixture.prompt
    assert '"chapter_track": null' in fixture.prompt
    assert '"slot_id": "legacy"' in fixture.prompt
    assert '"allowed_block_kinds"' in fixture.prompt
    assert "Narration slot contexts:" in fixture.prompt
    assert "numeric `track_index`" in fixture.prompt