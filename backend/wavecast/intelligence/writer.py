"""Tool-free narration writer over a scoped evidence set."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from wavecast.narration_quality import (
    CHARS_PER_SECOND,
    FILLER,
    check_block,
    rewrite_reasons,
    years_in,
)
from wavecast.presentation import HostMode, host_mode_prompt_guidance
from wavecast.programme_date import programme_date
from wavecast.providers.errors import ProviderInvalidResponseError
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.spoken_form import KnownTrack, has_unspeakable_script, to_spoken_form
from wavecast.stations import StationId, compose_signoff

from .fact_support import (
    FactChecker,
    FactReport,
    split_sentences,
    with_carried_risks,
    without_flagged_sentences,
)
from .fast_start import FastStructuredProvider
from .models import (
    ChapterPlan,
    Evidence,
    NarrationScript,
    NarrationSlotContext,
    OutputLanguage,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    resolve_output_language,
)
from .track_research import TalkingPoint
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
    def __init__(
        self,
        llm: FastStructuredProvider,
        *,
        max_revisions: int = 1,
        fact_checker: FactChecker | None = None,
    ) -> None:
        self.llm = llm
        self.fact_checker = fact_checker
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
        unfulfilled_artists: Sequence[str] = (),
        topic: str = "",
        slot_context: NarrationSlotContext | None = None,
        slot_contexts: Sequence[NarrationSlotContext] | None = None,
        inference_profile: InferenceProfile = InferenceProfile.SYNTHESIS,
        track_points: Sequence[TalkingPoint] | None = None,
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
        if (
            track_points is not None
            and not track_points
            and slots
            and not any(slot.is_final or slot.is_opening for slot in slots)
        ):
            # Track research ran and found nothing checkable about this track.  A block would
            # have nothing to say but filler ("接着听", "也一样"), which is worse than the music.
            logger.info("writer_skipped reason=no_verified_points")
            return RadioScript(blocks=[], intended_duration_seconds=1)
        spoken_window = (
            window_for(station, target_duration_seconds)
            if selected_language is OutputLanguage.ZH_CN
            else target_duration_seconds
        )
        # The closing's sign-off is added by the application after the Writer's text, so the
        # Writer's share of the window is what remains.
        signoff = (
            compose_signoff(station, voice_seed or topic or chapter.reason)
            if selected_language is OutputLanguage.ZH_CN and any(slot.is_final for slot in slots)
            else None
        )
        writer_window = spoken_window
        if signoff and spoken_window is not None:
            writer_window = max(4.0, spoken_window - len(signoff) / CHARS_PER_SECOND)
        station_line = (
            voice_instructions(
                station=station,
                seed=voice_seed or topic or chapter.reason,
                index=chapter.index,
                window_seconds=writer_window,
                used_openers=used_openers,
                is_opening=any(slot.is_opening for slot in slots),
                is_final=any(slot.is_final for slot in slots),
                has_points=bool(track_points),
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
        if unfulfilled_artists:
            route_line += (
                "The listener asked for "
                + ", ".join(unfulfilled_artists[:4])
                + ", but this programme does not play them. Never say or imply that the "
                "programme covers, includes, or is heading to them, and never describe the "
                "programme as a route that reaches them.\n"
            )
        if track_points is not None:
            if track_points:
                route_line += (
                    "Verified points about this chapter's track (each one is stated by a source and "
                    "was checked; say them in your own words, no need to say where they come from): "
                    + " | ".join(
                        point.text
                        if point.scope == "track"
                        else (
                            f"(programme background about the person or the period, not about the song "
                            f"that plays: tell it as a story and never call it 这首歌) {point.text}"
                            if point.scope == "background"
                            else f"(about the album or film, not the song) {point.text}"
                        )
                        for point in track_points
                    )
                    + ". Build this chapter's talk around one of them; one is enough, told in two or "
                    "three short sentences: what happened, one concrete detail, and why it is worth "
                    "hearing here. Do not infer what a song means from it. Add only listening cues "
                    "and transitions of your own; every other factual statement needs support in "
                    "the scoped evidence.\n"
                )
            else:
                route_line += (
                    "No source says anything checkable about this chapter's track. Keep the talk "
                    "to a short transition or something to listen for in the music; state no "
                    "facts about the song, who made it, what it comes from or its history.\n"
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
            "Each block must make sense on its own: the listener may not have heard the "
            "host's earlier lines (they can be skipped), so never refer back to something "
            "said before (‘这种…’, ‘刚才说到的…’, ‘前面提到的…’). The only earlier thing you may "
            "assume is the track in `just_played_track`. "
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
            "The voice speaks only Chinese and English, so keep Japanese, Korean and every other "
            "script out of what is spoken. The application says a song or artist whose name is in "
            "such a script as 这首歌 / 这位艺人, unless the slot context gives that track a "
            "`spoken_title`: that is the catalog's own Chinese title, so use it, in 《》, wherever "
            "you name the song. For a work (a film, a series, an album) use its "
            "established Chinese title (千与千寻, 龙猫, 天空之城) when you are sure of it. For a song "
            "title with no established Chinese title you may say once, in plain Chinese, what it "
            "means: “这首歌的名字，中文意思是……”, only when you are confident of the meaning; "
            "otherwise just call it 这首歌. Never write the original title or a pronunciation "
            "(romaji, pinyin of Japanese) in the spoken text, and do not invent a Chinese title.\n"
            "Facts: state only what the scoped evidence states. `canonical_artist` in a slot context is the "
            "performer the catalog credits for that recording; it is not necessarily the composer, "
            "lyricist or author, and not necessarily the subject of this programme. Who composed, wrote, "
            "sang, directed or released something, which film or album a piece belongs to, dates, and how a "
            "piece was made are facts: say them only when the evidence says so, and otherwise leave them "
            "out. When a track by another artist plays in a programme about one artist, never credit that "
            "track's composition, authorship or performance to the programme's subject unless the "
            "evidence says so. Put a song's name in 《》 only as the slot context gives it "
            "(`canonical_title` or `spoken_title`); a work the evidence names (a film, an album) may be "
            "named as the evidence names it.\n"
            f"{language_guidance}\n"
            f"{station_line}"
            f"{route_line}"
            f"Programme date: {programme_date()}. Publication dates are in each evidence item's published_at when "
            "known; the retrieval time is not one. Do not use words that depend on when it is now (最近, 上个月, "
            "目前, 如今, 新专辑, 最新...): say when something happened, or say nothing about when. A person who has "
            "died (when the evidence or the previous context says so) is spoken of in the past tense.\n"
            "Previous host lines of this programme, verbatim and in order (the text is for continuing the story "
            "smoothly and for not repeating or contradicting it; every fact you state must still come from the "
            f"evidence below): {previous_committed_context or '(none yet: the programme has just begun)'}\n"
            f"Chapter: {chapter.model_dump_json()}\n"
            f"Evidence: {[item.model_dump() for item in scoped]}\n"
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
        if any(slot.is_final for slot in slots):
            # A closing may name any song of the programme, so the application must be able
            # to say any of them (or replace the title) rather than drop the closing.
            known = {(track.artist, track.title) for track in known_tracks}
            for label in route_tracks:
                artist, _sep, title = label.partition(" - ")
                if title and (artist, title) not in known:
                    known.add((artist, title))
                    known_tracks.append(KnownTrack(artist=artist, title=title))
        route_titles = [label.split(" - ", 1)[-1] for label in route_tracks]
        # The tracks this slot is about, and the other songs of the programme: a statement may
        # not rest on material about one of the latter (the final slot may refer to any).
        focus_known: list[KnownTrack] = []
        other_known: list[KnownTrack] = []
        if slots and not any(slot.is_final for slot in slots):
            focus_known = [
                KnownTrack(artist=track.canonical_artist, title=track.canonical_title, spoken_title=track.spoken_title)
                for slot in slots
                for track in (slot.chapter_track, slot.just_played_track, slot.upcoming_track)
                if track is not None
            ]
            focus_titles_now = {track.title for track in focus_known}
            for label in route_tracks:
                artist, _sep, title = label.partition(" - ")
                if title and title not in focus_titles_now:
                    other_known.append(KnownTrack(artist=artist, title=title))
        supported = _supported_years(scoped, previous_committed_context, known_tracks)
        # The Writer is not given the played file's length, and a length found in the evidence is
        # usually the album version's; a wrong length is plain to the listener on the progress
        # bar.  So no length may be stated.
        supported_durations: set[str] = set()
        result = await self._attempt(prompt, chapter, evidence, known_tracks, inference_profile)
        report: FactReport | None = None

        rule_problem_count = [0]  # problems of the last review that a rewrite can fix (not unsupported facts)

        async def review(draft: RadioScript) -> tuple[dict[int, list[str]], FactReport | None]:
            found = _problems(
                draft,
                writer_window,
                known_tracks,
                slots,
                supported_years=supported,
                supported_durations=supported_durations,
                unplayed_names=unplayed_artists,
                route_titles=route_titles,
                earlier=previous_committed_context,
            )
            rule_problem_count[0] = sum(len(item) for item in found.values())
            fact_report = None
            if self.fact_checker is not None:
                fact_report = await self.fact_checker.review(
                    draft,
                    scoped,
                    tracks=known_tracks,
                    route_labels=route_tracks,
                    context=previous_committed_context,
                    known_text=evidence,
                    focus_tracks=focus_known,
                    other_tracks=other_known,
                )
                for issue in fact_report.issues:
                    found.setdefault(issue.block, []).append(issue.message)
            return found, fact_report

        for _ in range(self.max_revisions):
            if not isinstance(result, RadioScript):
                break
            problems, report = await review(result)
            if not problems:
                break
            if rule_problem_count[0] == 0:
                # Only unsupported facts are left: the evidence does not say them, so another wording
                # cannot make them supported. The sentences are removed below instead of rewritten.
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
            revised_problems, revised_report = await review(revised)
            logger.info(
                "writer_revision problems_before=%d problems_after=%d",
                sum(len(item) for item in problems.values()),
                sum(len(item) for item in revised_problems.values()),
            )
            if sum(len(item) for item in revised_problems.values()) < sum(
                len(item) for item in problems.values()
            ):
                result, report = revised, revised_report
            elif report is not None and revised_report is not None:
                # The earlier draft stays, but what the rewrite's check found wrong in the same
                # claims must not be forgotten (the two checks may disagree about one sentence).
                report = with_carried_risks(result, report, revised_report)
            break
        if report is None and isinstance(result, RadioScript) and self.fact_checker is not None:
            # No rewrite round ran (none allowed), so the draft has not been checked yet.
            _problems_unused, report = await review(result)
        if isinstance(result, RadioScript) and report is not None:
            result = without_flagged_sentences(result, report, known_tracks)
        if isinstance(result, RadioScript):
            result = _without_misplaced(result, known_tracks, slots, route_titles)
            result = _without_filler(result)
            result = _without_identity_conflicts(result, known_tracks, unplayed_artists)
            result = _without_unspeakable(result, known_tracks)
            if signoff:
                result = _with_signoff(
                    result, signoff, writer_window, closing=_route_closing(known_tracks, route_tracks)
                )
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
                # A block the voice cannot read is kept here: the rewrite step can still ask
                # for it in Chinese, and only what is still unreadable after that is dropped.
                spoken = to_spoken_form(block.text, known_tracks, tts_text=block.tts_text)
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


def _without_identity_conflicts(
    script: RadioScript, tracks: Sequence[KnownTrack], unplayed_names: Sequence[str]
) -> RadioScript:
    """Drop the blocks that still talk about an artist the listener will not hear.

    The one bounded rewrite either fixed it or did not.  A host that names an artist the
    programme does not play is wrong in a way no style fix repairs, so the block goes and the
    music plays on; music continuity wins over optional narration.
    """

    if not unplayed_names:
        return script
    kept = []
    for block in script.blocks:
        found = [
            issue
            for issue in check_block(
                block.text, tts_text=block.tts_text, tracks=tracks, unplayed_names=unplayed_names
            ).issues
            if issue.startswith("mentions_unplayed")
        ]
        if found:
            logger.warning(
                "writer_block_dropped reason=mentions_unplayed kind=%s count=%d",
                block.kind.value,
                len(found),
            )
            continue
        kept.append(block)
    if len(kept) == len(script.blocks):
        return script
    return script.model_copy(update={"blocks": kept})


def _without_filler(script: RadioScript) -> RadioScript:
    """Remove sentences that only say songs sit together or follow each other."""

    blocks = []
    for block in script.blocks:
        sentences = split_sentences(block.text)
        kept = [item for item in sentences if not FILLER.search(item)]
        if len(kept) == len(sentences):
            blocks.append(block)
            continue
        logger.info("writer_filler_removed kind=%s removed=%d", block.kind.value, len(sentences) - len(kept))
        text = "".join(kept).strip()
        if not text:
            continue
        blocks.append(block.model_copy(update={"text": text, "tts_text": None}))
    return script.model_copy(update={"blocks": blocks})


def _without_misplaced(
    script: RadioScript,
    tracks: Sequence[KnownTrack],
    slots: Sequence[NarrationSlotContext],
    route_titles: Sequence[str],
) -> RadioScript:
    """Drop the blocks that still talk about another song of the route after the rewrite."""

    if any(slot.is_final for slot in slots):
        return script
    focus = [
        track.canonical_title
        for slot in slots
        for track in (slot.just_played_track, slot.upcoming_track)
        if track is not None
    ]
    kept = []
    for block in script.blocks:
        check = check_block(
            block.text, tracks=tracks, route_titles=route_titles, focus_titles=focus
        )
        if any(issue.startswith("names_other_track") for issue in check.issues):
            logger.warning("writer_block_dropped reason=names_other_track kind=%s", block.kind.value)
            continue
        kept.append(block)
    if len(kept) == len(script.blocks):
        return script
    return script.model_copy(update={"blocks": kept})


def _without_unspeakable(script: RadioScript, tracks: Sequence[KnownTrack]) -> RadioScript:
    """Drop the blocks the voice still cannot read after the rewrite."""

    kept = []
    for block in script.blocks:
        if to_spoken_form(block.text, tracks, tts_text=block.tts_text).ok:
            kept.append(block)
        else:
            logger.warning("writer_block_dropped reason=unspeakable_script kind=%s", block.kind.value)
    if len(kept) == len(script.blocks):
        return script
    return script.model_copy(update={"blocks": kept})


def fallback_closing(
    station: StationId | None,
    voice_seed: str,
    slot_contexts: Sequence[NarrationSlotContext],
    route_tracks: Sequence[str],
) -> RadioScript | None:
    """The programme's closing when the Writer could not produce one: route plus sign-off.

    Built only from what the application knows, so it cannot be wrong; None for a station
    that says no sign-off (夜里) or a programme with no station.
    """

    signoff = compose_signoff(station, voice_seed)
    if not signoff:
        return None
    return _with_signoff(
        RadioScript(blocks=[], intended_duration_seconds=1),
        signoff,
        closing=_route_closing(_known_tracks(slot_contexts), route_tracks),
    )


def _route_closing(known_tracks: Sequence[KnownTrack], route_tracks: Sequence[str]) -> str:
    """A closing that states only what the application knows: where the route began and ended.

    Used when the Writer's closing did not survive the fact check, so a programme still ends on
    the route rather than on the station's name alone.  Songs whose names the voice cannot read
    are not named.
    """

    spoken_by_label = {
        f"{track.artist} - {track.title}": track.spoken_title for track in known_tracks if track.spoken_title
    }

    def name(label: str) -> str | None:
        title = label.split(" - ", 1)[-1]
        said = spoken_by_label.get(label) or (None if has_unspeakable_script(title) else title)
        return f"《{said}》" if said else None

    if len(route_tracks) >= 2:
        first, last = name(route_tracks[0]), name(route_tracks[-1])
        if first and last and first != last:
            return f"这一程从{first}听到{last}，就走到这里。"
    return "这一程就走到这里。"


def _with_signoff(
    script: RadioScript,
    signoff: str,
    window_seconds: float | None = None,
    closing: str = "",
) -> RadioScript:
    """Close the programme's last block with the station's sign-off.

    A closing that did not survive (dropped, or never written) is replaced by the sign-off
    alone: a programme always ends with the station saying so.
    """

    if not script.blocks:
        text = f"{closing}{signoff}" if closing else signoff
        seconds = max(2, round(len(text) / CHARS_PER_SECOND) + 1)
        return script.model_copy(
            update={
                "blocks": [
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.OUTRO, text=text, duration_seconds=seconds
                    )
                ]
            }
        )
    *rest, last = script.blocks
    text = last.text.rstrip()
    if text and text[-1] not in "。！？.!?":
        text += "。"
    tts = None
    if last.tts_text:
        tts = last.tts_text.rstrip()
        if tts and tts[-1] not in "。！？.!?":
            tts += "。"
        tts += signoff
    closed = last.model_copy(update={"text": text + signoff, "tts_text": tts})
    return script.model_copy(update={"blocks": [*rest, closed]})


def _problems(
    script: RadioScript,
    window_seconds: float | None,
    tracks: Sequence[KnownTrack],
    slots: Sequence[NarrationSlotContext],
    *,
    supported_years: set[str] | None = None,
    supported_durations: set[str] | None = None,
    unplayed_names: Sequence[str] = (),
    route_titles: Sequence[str] = (),
    earlier: str = "",
) -> dict[int, list[str]]:
    """Per-block reasons a rewrite is worth asking for (empty when the draft is fine)."""

    is_final = any(slot.is_final for slot in slots)
    focus_titles = [
        track.canonical_title
        for slot in slots
        for track in (slot.just_played_track, slot.upcoming_track)
        if track is not None
    ]
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
                supported_durations=supported_durations,
                unplayed_names=unplayed_names,
                route_titles=route_titles,
                focus_titles=focus_titles,
                earlier=earlier,
            )
        )
        spoken = to_spoken_form(block.text, tracks, tts_text=block.tts_text)
        if not spoken.ok:
            reasons = [
                *reasons,
                "The voice cannot read "
                + ", ".join(spoken.unspeakable[:4])
                + " (Japanese, Korean or another script). Say it in Chinese: the established "
                "Chinese name of the film, work or person; for a song title with none, say once "
                "“这首歌的名字，中文意思是……” if you are sure of the meaning, otherwise just "
                "这首歌 / 这位艺人; never write kana or hangul.",
            ]
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
                tracks.setdefault(
                    key,
                    KnownTrack(artist=key[0], title=key[1], spoken_title=track.spoken_title),
                )
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
