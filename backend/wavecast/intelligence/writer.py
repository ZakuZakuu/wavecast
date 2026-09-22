"""Tool-free narration writer over a scoped evidence set."""

from __future__ import annotations

import json
from collections.abc import Sequence

from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport

from .fast_start import FastStructuredProvider
from .models import (
    ChapterPlan,
    Evidence,
    NarrationScript,
    NarrationSlotContext,
    OutputLanguage,
    RadioScript,
    resolve_output_language,
)

ZH_CN_RADIO_WRITING_GUIDANCE = (
    "For zh-CN narration only, apply these concise radio-writing constraints: "
    "先说具体可听的声音，再给出较大的风格或文化解释；有证据时优先给一个 listener 能实际听到的 "
    "listen-for cue，但证据不足时宁可简单准确，不要编造听觉或事实细节。背景事实必须服务于当前听感 "
    "或下一首的连接。一个 block 只完成一个主要 editorial action；使用短分句、自然停顿和口语中文， "
    "减少论文腔与名词化。区分事实、听感和编辑判断，文化描述具体克制，避免宽泛的族群化概括。 "
    "TRACK_INTRO/TRANSITION 要说明下一首为什么值得听；通常用 2–4 个短句、约 20–35 秒，先给 concrete listen-for 再给最多一个必要背景解释，编辑动作完成就停，不要扩写成 40–50 秒。OUTRO 回扣本期 thesis 或前面真实听到的细节；如果上下文提供了已经听过的中间 artist/track/listen-for detail，至少具体回扣其中一个再落回 thesis，不要用模板式总结。 "
    "不要用模板式总结。不要为了高级感强造比喻、大词或结论。"
)


class WriterService:
    def __init__(self, llm: FastStructuredProvider) -> None:
        self.llm = llm

    async def write(
        self,
        chapter: ChapterPlan,
        evidence: list[Evidence],
        *,
        previous_committed_context: str = "",
        next_track_metadata: str = "",
        host_style: str = "warm, concise, spoken",
        target_duration_seconds: int | None = None,
        output_language: OutputLanguage = OutputLanguage.AUTO,
        topic: str = "",
        slot_context: NarrationSlotContext | None = None,
        slot_contexts: Sequence[NarrationSlotContext] | None = None,
    ) -> RadioScript | NarrationScript:
        scoped = [item for item in evidence if item.id in set(chapter.evidence_ids)]
        selected_language = resolve_output_language(output_language, topic or chapter.reason)
        if slot_context is not None and slot_contexts is not None:
            raise ValueError("pass slot_context or slot_contexts, not both")
        if slot_context is not None:
            slot_contexts = [slot_context]
        empty_scope_instruction = (
            "The evidence scope is empty. Do not make concrete factual, causal, date, "
            "statistical, or biographical claims. Keep narration to supportable transition, "
            "track adjacency, clearly marked editorial framing, or explicit uncertainty."
            if not scoped
            else ""
        )
        playback_context = (
            [context.model_dump(mode="json") for context in slot_contexts]
            if slot_contexts is not None
            else [
                {
                    "slot_id": "legacy",
                    "chapter_index": chapter.index,
                    "placement": "after_track",
                    "allowed_block_kinds": ["intro", "track_intro", "transition", "outro"],
                    "chapter_track": None,
                    "just_played_track": None,
                    "upcoming_track": next_track_metadata or None,
                    "is_opening": chapter.index == 0,
                    "is_final": False,
                }
            ]
        )
        language_guidance = (
            ZH_CN_RADIO_WRITING_GUIDANCE
            if selected_language is OutputLanguage.ZH_CN
            else ""
        )
        prompt = (
            "Write a structured radio script for this chapter, not an article. Use only the "
            "scoped evidence; keep factual claims separately identified by evidence IDs, avoid "
            "citation language in spoken text, and do not browse or change the selected track. "
            "Return ordered blocks using only intro, track_intro, transition, or outro. Each "
            "block must be speakable and independently timed. The chapter is a "
            "narrative beat and may have no playable track; do not invent or substitute a song. "
            "Treat the allocated narration duration as a soft pacing guide, not a quota: stop when the editorial action is complete and do not add background facts just to fill time. "
            "Keep `text` as the listener-visible copy and optionally provide `tts_text` when "
            "spoken pronunciation should differ. For example, display `3rd Coast` but use "
            "`Third Coast` for TTS. Do not use broad regex or dictionary substitutions. "
            "The application has assigned the narration slot below from resolved playback "
            "state. Use `just_played_track` for references such as ‘刚才这首’ and "
            "`upcoming_track` for references such as ‘下一首’; a null value means no such "
            "track exists. Do not infer adjacency from the chapter index, and do not assign "
            "or guess a numeric `track_index`; the application places every block. "
            "For each returned block, use only a kind listed in exactly one matching "
            "slot's `allowed_block_kinds`; a block kind is the typed placement contract, "
            "not a free editorial hint. Distinguish fact, correlation, causal claim, "
            "editorial interpretation, and uncertainty in `claim_support`; every support "
            "record must cite one or more IDs from this chapter's scoped evidence, and a "
            "correlation must not be phrased as proven causation. "
            "Cardinality is also part of the slot contract: return at most one block for "
            "each provided slot, never multiple blocks for the same slot, and do not add "
            "extra blocks just to fill the target duration. The single final narration "
            "slot is marked `is_final: true` and must return exactly one `outro` block; "
            "do not return any additional block for that final slot. "
            f"{empty_scope_instruction}\n"
            f"Write in output language {selected_language.value}.\n"
            f"{language_guidance}\n"
            f"Chapter: {chapter.model_dump_json()}\n"
            f"Evidence: {[item.model_dump() for item in scoped]}\n"
            f"Previous context: {previous_committed_context[:1000]}\n"
            f"Narration slot contexts: {json.dumps(playback_context, ensure_ascii=False)}\n"
            # Keep the old projection for compatibility with fixture callers;
            # it is explicitly not authoritative when typed slot contexts are present.
            "The following legacy field is informational only and must not override the "
            "resolved slot context.\n"
            f"Next track metadata: {next_track_metadata[:500]}\n"
            f"Host style: {host_style}\n"
            f"Target narration duration seconds: {target_duration_seconds or 'use chapter context'}"
        )
        result = await self.llm.structured(
            prompt,
            RadioScript,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=InferenceProfile.SYNTHESIS,
            stage="writer",
        )
        if not isinstance(result, (RadioScript, NarrationScript)):
            raise TypeError("writer returned an unexpected output model")
        _validate_evidence_references(result, chapter, evidence)
        if isinstance(result, RadioScript):
            # Numeric playback placement is application-owned.  Strip any
            # compatibility field emitted by an older/faulty structured model
            # before assembly normalizes the parsed blocks into this slot.
            result = result.model_copy(
                update={
                    "blocks": [block.model_copy(update={"track_index": None}) for block in result.blocks]
                }
            )
        return result


def _validate_evidence_references(
    result: RadioScript | NarrationScript,
    chapter: ChapterPlan,
    evidence: Sequence[Evidence],
) -> None:
    available = {item.id for item in evidence}
    scoped = set(chapter.evidence_ids)
    if not scoped <= available:
        raise ProviderInvalidResponseError("writer chapter referenced unavailable evidence")

    def validate(ids: Sequence[str]) -> None:
        referenced = set(ids)
        if not referenced <= scoped or not referenced <= available:
            raise ProviderInvalidResponseError("writer cited evidence outside chapter scope")

    validate(result.evidence_ids)
    if isinstance(result, NarrationScript):
        return
    for block in result.blocks:
        validate(block.evidence_ids)
        for support in block.claim_support:
            validate(support.evidence_ids)
