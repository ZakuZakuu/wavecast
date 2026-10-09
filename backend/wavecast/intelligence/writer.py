"""Tool-free narration writer over a scoped evidence set."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from wavecast.narration_quality import check_block, rewrite_reasons, years_in
from wavecast.presentation import HostMode, host_mode_prompt_guidance
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.spoken_form import KnownTrack, to_spoken_form
from wavecast.stations import StationId

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
from .voice import voice_instructions, window_for

logger = logging.getLogger(__name__)

ZH_CN_RADIO_WRITING_GUIDANCE = (
    "For zh-CN narration only, apply these constraints: "
    "说人话：口语、短分句、日常动词，一句话只说一件事，不用论文腔和名词化。"
    "要具体：用人名、年份、版本、谁演奏，不要堆形容词；证据不足时宁可简单准确，"
    "不要编造听觉或事实细节。区分事实、听感和编辑判断，文化描述具体克制，避免宽泛的族群化概括。"
    "一个 block 只完成一个主要动作，完成就停；时长服从 presentation mode 和 application 给出的 target。"
    "OUTRO 回扣本期 thesis 或前面真实听到的细节；如果上下文提供了已经听过的中间 "
    "artist/track/listen-for detail，至少具体回扣其中一个再落回 thesis，不要用模板式总结。"
    "不要为了高级感强造比喻、大词或结论。"
    "口播里不要交代依据或确定程度，例如“不是证据上的结论”“资料显示”“据说”；没有把握的内容直接不说，"
    "或只说你在听感上确实能描述的部分。"
)


class WriterService:
    def __init__(self, llm: FastStructuredProvider, *, max_revisions: int = 1) -> None:
        self.llm = llm
        # Bounded cost: at most this many extra Writer calls when a draft has the problems
        # narration_quality can detect (stock phrasing, invented memories, too long...).
        self.max_revisions = max_revisions

    async def write(
        self,
        chapter: ChapterPlan,
        evidence: list[Evidence],
        *,
        previous_committed_context: str = "",
        next_track_metadata: str = "",
        host_style: str = "warm, concise, spoken",
        host_mode: HostMode = HostMode.LIGHT,
        target_duration_seconds: int | None = None,
        output_language: OutputLanguage = OutputLanguage.AUTO,
        station: StationId | None = None,
        voice_seed: str = "",
        used_openers: Sequence[str] = (),
        route_tracks: Sequence[str] = (),
        unplayed_artists: Sequence[str] = (),
        topic: str = "",
        slot_context: NarrationSlotContext | None = None,
        slot_contexts: Sequence[NarrationSlotContext] | None = None,
        inference_profile: InferenceProfile = InferenceProfile.SYNTHESIS,
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
            "track adjacency, clearly marked editorial framing, or explicit uncertainty. "
            "Leave every `evidence_ids` list and `claim_support` empty: there is nothing to cite."
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
        slots = list(slot_contexts or ())
        spoken_window = (
            window_for(station, target_duration_seconds)
            if selected_language is OutputLanguage.ZH_CN
            else target_duration_seconds
        )
        station_line = (
            voice_instructions(
                station=station,
                seed=voice_seed or topic or chapter.reason,
                index=chapter.index,
                window_seconds=spoken_window,
                used_openers=used_openers,
                is_opening=any(slot.is_opening for slot in slots),
                is_final=any(slot.is_final for slot in slots),
            )
            if selected_language is OutputLanguage.ZH_CN and (station is not None or voice_seed)
            else (f"Station: {station.value}\n" if station is not None else "")
        )
        route_line = ""
        if route_tracks:
            route_line += (
                "Tracks in this programme, the only ones that are played: "
                + "; ".join(route_tracks[-24:])
                + ". Never say or imply that the listener heard or will hear anything else.\n"
            )
        if unplayed_artists:
            route_line += (
                "Planned earlier but NOT in this programme; do not mention them: "
                + ", ".join(unplayed_artists[:12])
                + ".\n"
            )
        language_guidance = (
            ZH_CN_RADIO_WRITING_GUIDANCE
            if selected_language is OutputLanguage.ZH_CN
            else ""
        )
        presentation_guidance = host_mode_prompt_guidance(host_mode)
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
            "do not return any additional block for that final slot. That outro closes the "
            "programme: it must not mention a next chapter, next track, a continuation or "
            "anything still to come. Spoken text must not discuss the status of the evidence "
            "or how certain a statement is; leave out what you cannot support. "
            f"{empty_scope_instruction}\n"
            f"Write in output language {selected_language.value}, whatever language the evidence "
            "or track titles use; keep artist and track names exactly as the slot contexts spell them. "
            "The application decides how songs and artists are spoken, so never translate or "
            "transliterate a title yourself, and keep Japanese, Korean or other non-Chinese, "
            "non-English text out of `tts_text`.\n"
            f"{language_guidance}\n"
            f"{station_line}"
            f"{route_line}"
            f"Chapter: {chapter.model_dump_json()}\n"
            f"Evidence: {[item.model_dump() for item in scoped]}\n"
            f"Previous context: {previous_committed_context[-1000:]}\n"
            f"Narration slot contexts: {json.dumps(playback_context, ensure_ascii=False)}\n"
            # Keep the old projection for compatibility with fixture callers;
            # it is explicitly not authoritative when typed slot contexts are present.
            "The following legacy field is informational only and must not override the "
            "resolved slot context.\n"
            f"Next track metadata: {next_track_metadata[:500]}\n"
            f"Host style: {host_style}\n"
            f"Presentation mode: {host_mode.value}. {presentation_guidance}\n"
            f"Target narration duration seconds: {spoken_window or 'use chapter context'}"
        )
        known_tracks = _known_tracks(slot_contexts)
        supported = _supported_years(scoped, previous_committed_context, known_tracks)
        result = await self._attempt(prompt, chapter, evidence, known_tracks, inference_profile)
        for _ in range(self.max_revisions):
            if not isinstance(result, RadioScript):
                break
            problems = _problems(
                result, spoken_window, known_tracks, slots, supported, unplayed_artists
            )
            if not problems:
                break
            revised = await self._attempt(
                _revision_prompt(prompt, result, problems),
                chapter,
                evidence,
                known_tracks,
                inference_profile,
            )
            if not isinstance(revised, RadioScript):
                break
            revised_problems = _problems(
                revised, spoken_window, known_tracks, slots, supported, unplayed_artists
            )
            logger.info(
                "writer_revision problems_before=%d problems_after=%d",
                sum(len(item) for item in problems.values()),
                sum(len(item) for item in revised_problems.values()),
            )
            if sum(len(item) for item in revised_problems.values()) < sum(
                len(item) for item in problems.values()
            ):
                result = revised
            break
        return result

    async def _attempt(
        self,
        prompt: str,
        chapter: ChapterPlan,
        evidence: list[Evidence],
        known_tracks: Sequence[KnownTrack],
        inference_profile: InferenceProfile,
    ) -> RadioScript | NarrationScript:
        result = await self.llm.structured(
            prompt,
            RadioScript,
            transport=StructuredTransport.RESPONSES_JSON_SCHEMA,
            profile=inference_profile,
            stage="writer",
        )
        if not isinstance(result, (RadioScript, NarrationScript)):
            raise TypeError("writer returned an unexpected output model")
        _validate_evidence_references(result, chapter, evidence)
        if isinstance(result, RadioScript):
            # Numeric playback placement is application-owned.  Strip any
            # compatibility field emitted by an older/faulty structured model
            # before assembly normalizes the parsed blocks into this slot.
            blocks = []
            for block in result.blocks:
                spoken = to_spoken_form(block.text, known_tracks, tts_text=block.tts_text)
                if not spoken.ok:
                    # The voice cannot read this; music continuity wins over optional narration.
                    logger.warning(
                        "writer_block_dropped reason=unspeakable_script kind=%s", block.kind.value
                    )
                    continue
                blocks.append(
                    block.model_copy(
                        update={
                            "track_index": None,
                            "tts_text": spoken.tts_text if spoken.tts_text != block.text else None,
                        }
                    )
                )
            return result.model_copy(update={"blocks": blocks})
        spoken = to_spoken_form(result.text, known_tracks, tts_text=result.tts_text)
        if not spoken.ok:
            logger.warning("writer_script_unspeakable_script")
        return result.model_copy(
            update={"tts_text": spoken.tts_text if spoken.tts_text != result.text else None}
        )


def _problems(
    script: RadioScript,
    window_seconds: float | None,
    tracks: Sequence[KnownTrack],
    slots: Sequence[NarrationSlotContext],
    supported_years: set[str] | None = None,
    unplayed_names: Sequence[str] = (),
) -> dict[int, list[str]]:
    """Per-block reasons a rewrite is worth asking for (empty when the draft is fine)."""

    is_final = any(slot.is_final for slot in slots)
    found: dict[int, list[str]] = {}
    for index, block in enumerate(script.blocks):
        reasons = rewrite_reasons(
            check_block(
                block.text,
                tts_text=block.tts_text,
                window_seconds=window_seconds,
                tracks=tracks,
                is_final=is_final,
                supported_years=supported_years,
                unplayed_names=unplayed_names,
            )
        )
        if reasons:
            found[index] = reasons
    return found


def _supported_years(
    evidence: Sequence[Evidence], previous_context: str, tracks: Sequence[KnownTrack]
) -> set[str]:
    """Years the Writer may state: those in its scoped evidence, earlier narration or titles."""

    texts = [item.claim_or_excerpt for item in evidence]
    texts.append(previous_context)
    texts.extend(f"{track.artist} {track.title}" for track in tracks)
    years: set[str] = set()
    for text in texts:
        years |= years_in(text)
    return years


def _revision_prompt(prompt: str, draft: RadioScript, problems: dict[int, list[str]]) -> str:
    lines = [
        prompt,
        "",
        "Your previous draft had these problems. Rewrite the blocks, keeping the same block "
        "kinds and the same facts, and fix every problem below. Do not add new problems.",
    ]
    for index, reasons in problems.items():
        block = draft.blocks[index]
        lines.append(f"Block {index + 1} ({block.kind.value}): {block.text}")
        lines.extend(f"  - {reason}" for reason in reasons)
    return "\n".join(lines)


def _known_tracks(slot_contexts: Sequence[NarrationSlotContext] | None) -> list[KnownTrack]:
    """Songs named by the slots: the only entities whose spoken form the application sets."""

    tracks: dict[tuple[str, str], KnownTrack] = {}
    for context in slot_contexts or ():
        for track in (context.chapter_track, context.just_played_track, context.upcoming_track):
            if track is not None:
                key = (track.canonical_artist, track.canonical_title)
                tracks.setdefault(key, KnownTrack(artist=key[0], title=key[1]))
    return list(tracks.values())


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
