"""Application-level assembly of a bounded, playable WaveCast episode.

The runtime and the intelligence services remain separate: this module is the
thin application seam that joins their provider-neutral contracts.  It never
promotes a proposal directly into playback; every chapter crosses the
deterministic catalog-resolution boundary first.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from pydantic import BaseModel, Field

from wavecast.composer import EpisodeComposer
from wavecast.intelligence.background import BackgroundIntelligencePipeline
from wavecast.intelligence.curation import CuratorContractError, CuratorService
from wavecast.intelligence.fast_start import FastPathCoordinator, FastPathResult, FastStartPlanner
from wavecast.intelligence.models import (
    ChapterPlan,
    EditorialConnection,
    Evidence,
    FastResearchInput,
    FastStartPlan,
    NarrationScript,
    NarrationSlotContext,
    NarrationSlotPlacement,
    NarrativeRole,
    NoveltyDistance,
    OutputLanguage,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResearchBundle,
    ResearchFacet,
    ResearchPlan,
    ResolvedTrack,
    TrackProposal,
    UnresolvedTrackError,
    resolve_output_language,
)
from wavecast.intelligence.research import (
    BackgroundResearchPlanner,
    BackgroundResearchService,
    FastResearchService,
    generic_research_plan,
)
from wavecast.intelligence.resolution import resolve_track_proposal_across_providers
from wavecast.intelligence.trace import GenerationTrace
from wavecast.intelligence.writer import WriterService
from wavecast.materialization import NarrationMaterializer
from wavecast.models.episode import LiveEpisode, NarrationSegment, PlayableEpisode, SegmentKind
from wavecast.orchestration.generation import GeneratedChapter
from wavecast.orchestration.staged import (
    ProgressiveAssemblyChapter,
    ProgressiveAssemblySession,
    ProgressiveSessionDiagnostic,
)
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import (
    ObjectStorageProvider,
    ProgressiveLLMProvider,
    SearchProvider,
    TTSProvider,
)
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import (
    ProviderError,
    ProviderSchemaValidationError,
)
from wavecast.providers.factory import build_music_registry
from wavecast.providers.fakes import (
    FakeSearchProvider,
    MockTTSProvider,
)
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.usage import UsageLedger, UsageTotals, usage_diagnostics
from wavecast.storage.assets import LocalObjectStorageProvider
from wavecast.timing import (
    ProgramTimingPlan,
    ProgramTimingSummary,
    build_program_timing_plan,
    summarize_program_timing,
)


class EpisodeAssemblyError(RuntimeError):
    """A typed failure at one deterministic assembly boundary."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        reason_code: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason_code = reason_code
        self.diagnostics = diagnostics or {}


class NarrationPlacementError(ValueError):
    """A parsed Writer block cannot be assigned to a deterministic slot."""


class LiveEpisodeAssemblyRequest(BaseModel):
    """Provider-neutral input for one bounded episode assembly run."""

    topic: str = Field(min_length=1, max_length=300)
    anchor_tracks: list[str] = Field(default_factory=list, max_length=8)
    desired_duration_seconds: int = Field(default=900, gt=0)
    max_tracks: int = Field(default=4, ge=2, le=8)
    max_chapters: int = Field(default=16, ge=2, le=32)
    listener_taste_context: str | None = Field(default=None, max_length=1000)
    output_language: OutputLanguage = OutputLanguage.AUTO


class UnresolvedAssemblyProposal(BaseModel):
    chapter_index: int = Field(ge=0)
    proposal: TrackProposal
    reason: str

    @property
    def resolution_status(self) -> str:
        return "unresolved"


class AssemblyTimings(BaseModel):
    fast_path_ms: int = Field(ge=0)
    background_research_ms: int = Field(ge=0)
    curator_ms: int = Field(ge=0)
    resolution_ms: int = Field(ge=0)
    writer_ms: int = Field(ge=0)
    composition_ms: int = Field(ge=0)
    narration_materialization_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)


class AssemblyDurationSummary(BaseModel):
    music_seconds: int = Field(ge=0)
    narration_seconds: int = Field(ge=0)
    total_seconds: int = Field(ge=0)
    narration_ratio: float = Field(ge=0, le=1)


class WriterChapterDiagnostic(BaseModel):
    """Safe parsed/normalized Writer data for one application chapter."""

    chapter_index: int = Field(ge=0)
    connection_from_previous_track: EditorialConnection | None = None
    available_slots: list[NarrationSlotContext] = Field(default_factory=list)
    parsed_blocks: list[RadioScriptBlock] = Field(default_factory=list)
    normalized_blocks: list[RadioScriptBlock] = Field(default_factory=list)
    normalized_slot_contexts: list[NarrationSlotContext] = Field(default_factory=list)


class EpisodeAssemblyResult(BaseModel):
    """Sanitized, inspectable output of one assembly run."""

    playable_episode: PlayableEpisode
    fast_plan: FastStartPlan
    skeleton: ProgramSkeleton
    resolved_tracks: list[ResolvedTrack]
    unresolved_proposals: list[UnresolvedAssemblyProposal] = Field(default_factory=list)
    radio_script: RadioScript
    timings: AssemblyTimings
    usage: UsageTotals
    duration_summary: AssemblyDurationSummary
    timing_plan: ProgramTimingPlan
    timing_summary: ProgramTimingSummary
    trace: GenerationTrace
    writer_chapters: list[WriterChapterDiagnostic] = Field(default_factory=list)
    research_plan: ResearchPlan | None = None
    research_evidence: list[Evidence] = Field(default_factory=list)
    usage_by_stage: dict[str, UsageTotals] = Field(default_factory=dict)
    provider_events: list[dict[str, object]] = Field(default_factory=list)
    progressive_session: ProgressiveAssemblySession | None = None


@dataclass(frozen=True)
class _ResolvedChapter:
    chapter: ChapterPlan
    writer_chapter: ChapterPlan
    track: ResolvedTrack | None
    music_index: int | None


@dataclass(frozen=True)
class _PreparedIntelligence:
    fast_result: FastPathResult
    bundle: ResearchBundle
    skeleton: ProgramSkeleton
    resolved_chapters: list[_ResolvedChapter]
    unresolved: list[UnresolvedAssemblyProposal]
    slot_contexts: list[list[NarrationSlotContext]]
    fast_path_ms: int
    background_research_ms: int
    curator_ms: int
    resolution_ms: int


_ESTIMATED_TRACK_DURATION_SECONDS = 180


class LiveEpisodeAssemblyService:
    """Join the existing fast/background intelligence and playback seams.

    This service owns application sequencing only.  It does not mutate an
    ``EpisodeOrchestrator`` or introduce a second lifecycle state machine.
    """

    def __init__(
        self,
        *,
        fast_path: FastPathCoordinator,
        background_pipeline: BackgroundIntelligencePipeline,
        retrieval: MusicRetrievalService,
        composer: EpisodeComposer,
        materializer: NarrationMaterializer,
        ledger: UsageLedger | None = None,
        narration_ratio: float = 0.15,
    ) -> None:
        self.fast_path = fast_path
        self.background_pipeline = background_pipeline
        self.retrieval = retrieval
        self.composer = composer
        self.materializer = materializer
        self.ledger = ledger or UsageLedger()
        if not 0.1 <= narration_ratio <= 0.2:
            raise ValueError("narration_ratio must be between 0.1 and 0.2")
        self.narration_ratio = narration_ratio

    async def prepare_progressive_session(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        opening_track: ResolvedTrack,
        request_id: str | None = None,
    ) -> ProgressiveAssemblySession:
        """Prepare serializable intelligence without producing future audio.

        The opening identity is application-owned and explicit. This seam ends
        before Writer, composition, TTS, and playback-asset preparation.
        """

        prepared = await self._prepare_intelligence(request, request_id=request_id)
        return _build_progressive_session(
            request=request,
            prepared=prepared,
            opening_track=opening_track,
            narration_ratio=self.narration_ratio,
        )

    def create_progressive_chapter_generator(
        self, session: ProgressiveAssemblySession
    ) -> StagedProgressiveChapterGenerator:
        """Create a one-chunk adapter without changing the default runtime."""

        return StagedProgressiveChapterGenerator(
            session=session,
            writer=self.background_pipeline.writer,
            composer=self.composer,
            materializer=self.materializer,
        )

    async def _prepare_intelligence(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        request_id: str | None = None,
    ) -> _PreparedIntelligence:
        """Run the bounded intelligence and catalog-identity stages only."""

        request_id = request_id or uuid4().hex
        intelligence_input = FastResearchInput(
            topic=request.topic,
            anchor_tracks=list(request.anchor_tracks),
            desired_duration_seconds=request.desired_duration_seconds,
            listener_taste_context=request.listener_taste_context,
            output_language=request.output_language,
        )

        fast_started = perf_counter()
        try:
            fast_result = await self.fast_path.run(intelligence_input, request_id=request_id)
        except ProviderError as error:
            raise EpisodeAssemblyError(str(error), stage="fast_start") from error
        fast_path_ms = _elapsed_ms(fast_started)
        trace = fast_result.trace

        background_started = perf_counter()
        trace.mark("assembly_background_started", max_tracks=request.max_tracks)
        try:
            bundle = await self.background_pipeline.research.run(
                intelligence_input,
                fast_result,
                cancel_event=asyncio.Event(),
                trace=trace,
            )
            if bundle is None:
                raise EpisodeAssemblyError("background research was cancelled", stage="background_research")
        except EpisodeAssemblyError:
            raise
        except ProviderError as error:
            raise EpisodeAssemblyError(str(error), stage="background_research") from error
        background_research_ms = _elapsed_ms(background_started)
        trace.mark("background_research_ready", elapsed_ms=background_research_ms)

        curator_started = perf_counter()
        trace.mark("curator_started")
        try:
            curator_plan = fast_result.plan
            if bundle.research_plan is not None:
                curator_plan = fast_result.plan.model_copy(
                    update={"research_plan": bundle.research_plan}
                )
            skeleton = await self.background_pipeline.curator.curate(
                bundle,
                curator_plan,
                desired_duration_seconds=request.desired_duration_seconds,
                max_tracks=request.max_tracks,
                max_chapters=request.max_chapters,
                output_language=resolve_output_language(request.output_language, request.topic),
                topic=request.topic,
                trace=trace,
            )
        except CuratorContractError as error:
            raise EpisodeAssemblyError(
                "curator contract validation failed",
                stage="curator",
                reason_code=error.reason_code,
                diagnostics={
                    "research_snapshot": _research_failure_snapshot(
                        fast_result, bundle, trace, self.ledger
                    ),
                    "curator_diagnostics": list(error.diagnostics),
                },
            ) from error
        except ProviderError as error:
            raise EpisodeAssemblyError(
                "curator provider response was invalid",
                stage="curator",
                reason_code=(
                    "curator_schema_invalid"
                    if isinstance(error, ProviderSchemaValidationError)
                    else None
                ),
                diagnostics={
                    "research_snapshot": _research_failure_snapshot(
                        fast_result, bundle, trace, self.ledger
                    )
                },
            ) from error
        curator_ms = _elapsed_ms(curator_started)
        chapters = _select_chapters_for_music_limit(
            skeleton.chapters, request.max_tracks, request.max_chapters
        )
        chapters = _normalize_chapters(chapters)
        skeleton = skeleton.model_copy(update={"chapters": chapters})
        trace.mark("program_skeleton_ready", chapter_count=len(chapters))

        resolution_started = perf_counter()
        resolved_chapters: list[_ResolvedChapter] = []
        unresolved: list[UnresolvedAssemblyProposal] = []
        for chapter in chapters:
            resolved: ResolvedTrack | None = None
            resolution_reason: str | None = None
            if chapter.track is not None:
                try:
                    resolved = await resolve_track_proposal_across_providers(
                        self.retrieval, chapter.track
                    )
                except ProviderError as error:
                    resolution_reason = f"resolution provider failed: {type(error).__name__}"
                if resolved is None and resolution_reason is None:
                    resolution_reason = "no exact playable catalog match"
                if resolution_reason is not None:
                    unresolved.append(
                        UnresolvedAssemblyProposal(
                            chapter_index=chapter.index,
                            proposal=chapter.track,
                            reason=resolution_reason,
                        )
                    )
            resolved_chapters.append(
                _ResolvedChapter(
                    chapter=chapter,
                    writer_chapter=chapter.model_copy(
                        update={
                            "index": len(resolved_chapters),
                            "track": chapter.track if resolved is not None else None,
                        }
                    ),
                    track=resolved,
                    music_index=None,
                )
            )
        resolved_chapters = _reindex_resolved_chapters(resolved_chapters)
        resolution_ms = _elapsed_ms(resolution_started)
        trace.mark(
            "tracks_resolved",
            resolved_count=sum(item.track is not None for item in resolved_chapters),
            unresolved_count=len(unresolved),
        )
        resolved_track_count = sum(item.track is not None for item in resolved_chapters)
        if resolved_track_count < 2:
            raise EpisodeAssemblyError(
                f"assembly requires at least two resolved tracks; got {resolved_track_count}",
                stage="resolution",
                reason_code="insufficient_resolved_tracks",
                diagnostics={
                    "resolved_track_count": resolved_track_count,
                    "unresolved_track_count": len(unresolved),
                    "required_resolved_track_count": 2,
                },
            )

        try:
            slot_contexts = _build_narration_slot_contexts(resolved_chapters)
        except NarrationPlacementError as error:
            raise EpisodeAssemblyError(
                str(error),
                stage="writer_normalization",
                reason_code="narration_slot_derivation_failed",
                diagnostics={"narration_failure_boundary": "slot_derivation"},
            ) from error

        return _PreparedIntelligence(
            fast_result=fast_result,
            bundle=bundle,
            skeleton=skeleton,
            resolved_chapters=resolved_chapters,
            unresolved=unresolved,
            slot_contexts=slot_contexts,
            fast_path_ms=fast_path_ms,
            background_research_ms=background_research_ms,
            curator_ms=curator_ms,
            resolution_ms=resolution_ms,
        )

    async def assemble(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        request_id: str | None = None,
    ) -> EpisodeAssemblyResult:
        started = perf_counter()
        request_id = request_id or uuid4().hex
        prepared = await self._prepare_intelligence(request, request_id=request_id)
        fast_result = prepared.fast_result
        bundle = prepared.bundle
        skeleton = prepared.skeleton
        resolved_chapters = prepared.resolved_chapters
        unresolved = prepared.unresolved
        slot_contexts = prepared.slot_contexts
        fast_path_ms = prepared.fast_path_ms
        background_research_ms = prepared.background_research_ms
        curator_ms = prepared.curator_ms
        resolution_ms = prepared.resolution_ms
        resolved_track_count = sum(item.track is not None for item in resolved_chapters)
        trace = fast_result.trace

        opening_track = next(
            (item.track for item in resolved_chapters if item.track is not None),
            None,
        )
        if opening_track is None:
            raise EpisodeAssemblyError(
                "assembly did not produce an application-owned opening track",
                stage="resolution",
                reason_code="missing_opening_track",
            )
        progressive_session = _build_progressive_session(
            request=request,
            prepared=prepared,
            opening_track=opening_track,
            narration_ratio=self.narration_ratio,
        )

        track_inputs = [item.track for item in resolved_chapters if item.track is not None]

        try:
            prepared_tracks = [
                item for item in await self.composer.prepare_tracks(track_inputs) if item is not None
            ]
        except (ProviderError, UnresolvedTrackError, ValueError) as error:
            raise EpisodeAssemblyError(str(error), stage="music_preparation") from error

        resolved_music_seconds = sum(item.asset.duration for item in prepared_tracks)
        timing_plan = build_program_timing_plan(
            desired_total_seconds=request.desired_duration_seconds,
            target_narration_ratio=self.narration_ratio,
            resolved_music_seconds=resolved_music_seconds,
            chapter_slot_counts=[len(contexts) for contexts in slot_contexts],
        )
        writer_started = perf_counter()
        writer_scripts: list[RadioScript | NarrationScript] = []
        previous_context = ""
        for index, resolved_chapter in enumerate(resolved_chapters):
            chapter_slots = slot_contexts[index]
            if not chapter_slots:
                writer_scripts.append(
                    RadioScript(blocks=[], intended_duration_seconds=1)
                )
                continue
            next_metadata = ""
            next_track = next(
                (
                    slot.upcoming_track
                    for slot in chapter_slots
                    if slot.placement is not NarrationSlotPlacement.BEFORE_TRACK
                    and slot.upcoming_track is not None
                ),
                None,
            )
            if next_track is not None:
                next_metadata = f"{next_track.canonical_artist} — {next_track.canonical_title}"
            try:
                script = await self.background_pipeline.writer.write(
                    resolved_chapter.writer_chapter,
                    bundle.evidence,
                    previous_committed_context=previous_context,
                    next_track_metadata=next_metadata,
                    target_duration_seconds=timing_plan.chapter_budgets[index].target_narration_seconds,
                    output_language=resolve_output_language(request.output_language, request.topic),
                    topic=request.topic,
                    slot_contexts=chapter_slots,
                )
            except ProviderError as error:
                raise EpisodeAssemblyError(str(error), stage="writer") from error
            writer_scripts.append(script)
            previous_context = _script_text(script)
        writer_ms = _elapsed_ms(writer_started)
        try:
            radio_script, writer_chapters = _assemble_writer_scripts(
                writer_scripts,
                resolved_track_count,
                chapter_music_indices=[item.music_index for item in resolved_chapters],
                slot_contexts=slot_contexts,
                chapter_connections=[
                    item.writer_chapter.connection_from_previous_track
                    for item in resolved_chapters
                ],
            )
        except NarrationPlacementError as error:
            raise EpisodeAssemblyError(
                str(error),
                stage="writer_normalization",
                reason_code="narration_slot_normalization_failed",
                diagnostics={"narration_failure_boundary": "writer_slot_normalization"},
            ) from error

        composition_started = perf_counter()
        try:
            playable_episode = self.composer.compose_prepared(prepared_tracks, radio_script)
        except (ProviderError, UnresolvedTrackError, ValueError) as error:
            raise EpisodeAssemblyError(str(error), stage="composition") from error
        composition_ms = _elapsed_ms(composition_started)
        _assert_narration_blocks_materialized(radio_script, playable_episode)

        narration_started = perf_counter()
        try:
            for segment in playable_episode.segments:
                if isinstance(segment, NarrationSegment):
                    await self.materializer.materialize(segment)
        except ProviderError as error:
            raise EpisodeAssemblyError(str(error), stage="narration_materialization") from error
        narration_ms = _elapsed_ms(narration_started)
        trace.mark("episode_ready", segment_count=len(playable_episode.segments))

        duration_summary = _duration_summary(playable_episode)
        timing_summary = summarize_program_timing(
            timing_plan,
            planned_narration_seconds=sum(
                block.intended_duration_seconds for block in radio_script.blocks
            ),
            actual_narration_seconds=duration_summary.narration_seconds,
            music_seconds=duration_summary.music_seconds,
        )
        usage_report = usage_diagnostics(self.ledger)
        return EpisodeAssemblyResult(
            playable_episode=playable_episode,
            fast_plan=fast_result.plan,
            skeleton=skeleton,
            resolved_tracks=[item.track for item in resolved_chapters if item.track is not None],
            unresolved_proposals=unresolved,
            radio_script=radio_script,
            timings=AssemblyTimings(
                fast_path_ms=fast_path_ms,
                background_research_ms=background_research_ms,
                curator_ms=curator_ms,
                resolution_ms=resolution_ms,
                writer_ms=writer_ms,
                composition_ms=composition_ms,
                narration_materialization_ms=narration_ms,
                total_ms=_elapsed_ms(started),
            ),
            usage=self.ledger.totals(),
            duration_summary=duration_summary,
            timing_plan=timing_plan,
            timing_summary=timing_summary,
            trace=trace,
            writer_chapters=writer_chapters,
            research_plan=bundle.research_plan or fast_result.plan.research_plan,
            research_evidence=list(bundle.evidence),
            usage_by_stage={
                stage: UsageTotals.model_validate(totals)
                for stage, totals in usage_report["usage_by_stage"].items()
            },
            provider_events=list(usage_report["provider_events"]),
            progressive_session=progressive_session,
        )

    async def run(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        request_id: str | None = None,
    ) -> EpisodeAssemblyResult:
        """Compatibility spelling for application callers that use service.run()."""
        return await self.assemble(request, request_id=request_id)

    async def aclose(self) -> None:
        """Close owned provider clients when a probe or worker is finished."""
        candidates = [
            self.fast_path.research.discovery,
            self.fast_path.research.research,
            self.background_pipeline.research.discovery,
            self.background_pipeline.research.research,
            self.background_pipeline.curator.llm,
            self.background_pipeline.writer.llm,
            self.composer.music_provider,
            self.materializer.tts_provider,
        ]
        closed: set[int] = set()
        for candidate in candidates:
            close = getattr(candidate, "aclose", None)
            if not callable(close) or id(candidate) in closed:
                continue
            closed.add(id(candidate))
            result = close()
            if hasattr(result, "__await__"):
                await result


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


_SAFE_TRACE_METADATA = {
    "fallback",
    "candidate_count",
    "chapter_count",
    "query_count",
    "elapsed_ms",
    "research_facet_count",
    "planned_background_query_count",
    "plan_source",
    "selected_queries",
    "chapter_index",
    "reference_kind",
    "dropped_reference_count",
    "remaining_reference_count",
    "reason",
}


def _safe_trace_snapshot(trace: GenerationTrace) -> list[dict[str, object]]:
    return [
        {
            "name": event.name,
            "elapsed_ms": event.elapsed_from_start_ms,
            "metadata": {
                key: value
                for key, value in event.metadata.items()
                if key in _SAFE_TRACE_METADATA
            },
        }
        for event in trace.events
    ]


def _safe_diagnostic_url(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))


def _safe_research_plan(plan: ResearchPlan | None) -> dict[str, object] | None:
    if plan is None:
        return None
    return {
        "central_question": plan.central_question,
        "research_mode": plan.research_mode.value,
        "no_research_reason": plan.no_research_reason,
        "facets": [
            {
                "id": facet.id,
                "label": facet.label,
                "question": facet.question,
                "priority": facet.priority,
                "source_preferences": list(facet.source_preferences),
            }
            for facet in plan.facets
        ],
        "background_queries": [
            {
                "query": query.query,
                "intent": query.intent.value,
                "facet_ids": list(query.facet_ids),
                "rationale": query.rationale,
            }
            for query in plan.background_queries
        ],
    }


def _safe_research_evidence(evidence: list[Evidence]) -> list[dict[str, object]]:
    return [
        {
            "id": item.id,
            "canonical_url": _safe_diagnostic_url(item.canonical_url or item.source_url),
            "source_domain": item.source_domain,
            "source_category": item.source_category.value,
            "source_preference_rank": item.source_preference_rank,
            "source_provider": item.source_provider,
            "source_title": item.source_title,
            "confidence": item.confidence,
            "facet_ids": list(item.facet_ids),
            "search_intent": item.search_intent.value if item.search_intent else None,
        }
        for item in evidence
    ]


def _research_plan_source(trace: GenerationTrace) -> str:
    for event in reversed(trace.events):
        if event.name in {"background_research_plan_fallback", "background_research_plan_regenerated"}:
            return str(event.metadata.get("plan_source", "unknown"))
        if event.name == "background_research_plan_used":
            return str(event.metadata.get("plan_source", "unknown"))
    return "unknown"


def _selected_background_queries(trace: GenerationTrace) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for event in trace.events:
        values = event.metadata.get("selected_queries")
        if isinstance(values, list):
            selected = [
                value
                for value in values
                if isinstance(value, dict)
                and isinstance(value.get("provider"), str)
                and isinstance(value.get("query"), str)
            ]
    return selected


def _research_failure_snapshot(
    fast_result: FastPathResult,
    bundle: ResearchBundle,
    trace: GenerationTrace,
    ledger: UsageLedger,
) -> dict[str, object]:
    usage_report = usage_diagnostics(ledger)
    fast_plan = getattr(fast_result, "plan", None)
    plan = bundle.research_plan or getattr(fast_plan, "research_plan", None)
    return {
        "fast": {
            "fallback": trace.fallback_used,
            "ttfs_ms": trace.time_to_first_script_ms,
            "fast_research_elapsed_ms": trace.fast_research_elapsed_ms,
            "fast_planner_started_ms": trace.fast_planner_started_ms,
        },
        "research_plan_source": _research_plan_source(trace),
        "research_plan": _safe_research_plan(plan),
        "selected_background_queries": _selected_background_queries(trace),
        "research_evidence": _safe_research_evidence(list(bundle.evidence)),
        "trace": _safe_trace_snapshot(trace),
        "usage_by_stage": usage_report["usage_by_stage"],
        "provider_events": usage_report["provider_events"],
    }




def _same_resolved_track(left: ResolvedTrack | None, right: ResolvedTrack) -> bool:
    """Compare catalog identity exactly; never fuzzy-dedupe an opening."""

    return (
        left is not None
        and left.track_ref == right.track_ref
        and left.canonical_artist == right.canonical_artist
        and left.canonical_title == right.canonical_title
    )


def _opening_chapter_plan(opening_track: ResolvedTrack) -> ChapterPlan:
    return ChapterPlan(
        index=0,
        track=TrackProposal(
            artist=opening_track.canonical_artist,
            title=opening_track.canonical_title,
            confidence=1.0,
            reasons=["Application-owned opening track."],
        ),
        narrative_role=NarrativeRole.ANCHOR,
        reason="Application-owned opening track for the progressive route.",
        narration_goal="Establish the listening route from the opening track.",
    )


def _normalize_opening_resolved_route(
    chapters: list[_ResolvedChapter],
    opening_track: ResolvedTrack,
) -> list[_ResolvedChapter]:
    """Put the application-owned opening first and remove exact duplicates."""

    opening_index = next(
        (
            index
            for index, item in enumerate(chapters)
            if _same_resolved_track(item.track, opening_track)
        ),
        None,
    )
    if opening_index is None:
        opening = _ResolvedChapter(
            chapter=_opening_chapter_plan(opening_track),
            writer_chapter=_opening_chapter_plan(opening_track),
            track=opening_track,
            music_index=None,
        )
    else:
        opening = chapters[opening_index]

    remainder = [
        item
        for index, item in enumerate(chapters)
        if index != opening_index and not _same_resolved_track(item.track, opening_track)
    ]
    return [opening, *remainder]


def _bound_progressive_resolved_route(
    chapters: list[_ResolvedChapter],
    *,
    max_tracks: int,
    max_chapters: int,
) -> list[_ResolvedChapter]:
    """Reapply request bounds after inserting the application-owned opening."""

    bounded: list[_ResolvedChapter] = []
    track_count = 0
    for item in chapters:
        if len(bounded) >= max_chapters:
            break
        if item.track is not None and track_count >= max_tracks:
            continue
        bounded.append(item)
        if item.track is not None:
            track_count += 1
    return bounded


def _reindex_resolved_chapters(
    chapters: list[_ResolvedChapter],
) -> list[_ResolvedChapter]:
    """Recompute route connections and music indices after normalization."""

    connections = _resolved_route_connections(chapters)
    indexed: list[_ResolvedChapter] = []
    music_index = 0
    for index, item in enumerate(chapters):
        chapter = item.chapter.model_copy(update={"index": index})
        writer_chapter = item.writer_chapter.model_copy(
            update={
                "index": index,
                "connection_from_previous_track": connections[index],
            }
        )
        indexed.append(
            _ResolvedChapter(
                chapter=chapter,
                writer_chapter=writer_chapter,
                track=item.track,
                music_index=music_index if item.track is not None else None,
            )
        )
        if item.track is not None:
            music_index += 1
    return indexed


def _build_progressive_session(
    *,
    request: LiveEpisodeAssemblyRequest,
    prepared: _PreparedIntelligence,
    opening_track: ResolvedTrack,
    narration_ratio: float,
) -> ProgressiveAssemblySession:
    """Build the pre-Writer session from route identities and slot contexts."""

    normalized = _reindex_resolved_chapters(
        _bound_progressive_resolved_route(
            _normalize_opening_resolved_route(prepared.resolved_chapters, opening_track),
            max_tracks=request.max_tracks,
            max_chapters=request.max_chapters,
        )
    )
    try:
        all_slot_contexts = _build_narration_slot_contexts(normalized)
    except NarrationPlacementError as error:
        raise EpisodeAssemblyError(
            str(error),
            stage="writer_normalization",
            reason_code="narration_slot_derivation_failed",
            diagnostics={"narration_failure_boundary": "slot_derivation"},
        ) from error

    runtime_future_pairs = [
        (item, contexts)
        for item, contexts in zip(normalized[1:], all_slot_contexts[1:], strict=True)
        if item.track is not None or contexts
    ]
    future = [item for item, _ in runtime_future_pairs]
    future_slots = [contexts for _, contexts in runtime_future_pairs]
    if not future:
        raise EpisodeAssemblyError(
            "progressive route has no future chapter after the opening",
            stage="resolution",
            reason_code="no_progressive_future_route",
        )

    future_music_count = sum(item.track is not None for item in future)
    timing_plan = build_program_timing_plan(
        desired_total_seconds=request.desired_duration_seconds,
        target_narration_ratio=narration_ratio,
        resolved_music_seconds=future_music_count * _ESTIMATED_TRACK_DURATION_SECONDS,
        chapter_slot_counts=[len(contexts) for contexts in future_slots],
    )
    session_chapters = [
        ProgressiveAssemblyChapter(
            chapter_id=f"chapter-{index + 2}",
            chapter=item.writer_chapter,
            resolved_track=item.track,
            slot_contexts=future_slots[index],
            target_narration_seconds=timing_plan.chapter_budgets[index].target_narration_seconds,
        )
        for index, item in enumerate(future)
    ]
    return ProgressiveAssemblySession(
        topic=request.topic,
        listener_taste_context=request.listener_taste_context,
        desired_duration_seconds=request.desired_duration_seconds,
        max_tracks=request.max_tracks,
        max_chapters=request.max_chapters,
        output_language=resolve_output_language(request.output_language, request.topic),
        opening_track_ref=opening_track.track_ref,
        fast_plan=prepared.fast_result.plan,
        research=prepared.bundle,
        skeleton=prepared.skeleton.model_copy(
            update={"chapters": [normalized[0].chapter, *[item.chapter for item in future]]}
        ),
        chapters=session_chapters,
        timing_plan=timing_plan,
        diagnostics=[
            ProgressiveSessionDiagnostic(
                code="unresolved_track",
                chapter_index=item.chapter_index,
                detail=item.reason,
            )
            for item in prepared.unresolved
        ],
    )


def _resolved_route_connections(
    chapters: list[_ResolvedChapter],
) -> list[EditorialConnection | None]:
    """Keep only selected-route connections that remain playable-route adjacency.

    Resolution may remove an intermediate selected track.  We clear stale
    metadata instead of inventing a new relation between surviving tracks.
    """

    connections: list[EditorialConnection | None] = []
    previous_selected_track_resolved = False
    for item in chapters:
        connection: EditorialConnection | None = None
        if item.chapter.track is not None:
            if item.track is not None and previous_selected_track_resolved:
                connection = item.chapter.connection_from_previous_track
            previous_selected_track_resolved = item.track is not None
        connections.append(connection)
    return connections


def _select_chapters_for_music_limit(
    chapters: list[ChapterPlan], max_tracks: int, max_chapters: int
) -> list[ChapterPlan]:
    """Keep every narrative-only beat while bounding track-bearing chapters."""

    selected: list[ChapterPlan] = []
    track_count = 0
    for chapter in chapters:
        if chapter.track is None or track_count < max_tracks:
            selected.append(chapter)
        if chapter.track is not None:
            track_count += 1
    return selected[:max_chapters]


def _normalize_chapters(chapters: list[ChapterPlan]) -> list[ChapterPlan]:
    """Assign contiguous application identity without mutating Curator models."""

    return [chapter.model_copy(update={"index": index}) for index, chapter in enumerate(chapters)]


def _build_narration_slot_contexts(
    chapters: list[_ResolvedChapter],
) -> list[list[NarrationSlotContext]]:
    """Derive truthful Writer slots with one owner per physical music gap.

    By default the upcoming playable chapter owns A -> B through its
    before-track slot.  If one or more narrative-only chapters intervene,
    those chapters own the gap instead.  The final tail is owned by the last
    chapter, so a final playable chapter cannot compete with a trailing
    narrative-only resolution chapter.
    """

    contexts: list[list[NarrationSlotContext]] = []
    owned_gap_keys: set[tuple[str, int | None, int | None]] = set()

    def claim_gap(
        kind: str,
        left_music_index: int | None,
        right_music_index: int | None,
        chapter_index: int,
    ) -> None:
        key = (kind, left_music_index, right_music_index)
        if key in owned_gap_keys:
            raise NarrationPlacementError(
                "physical playback gap has multiple narration owners "
                f"(kind={kind}, left={left_music_index}, right={right_music_index}, "
                f"chapter={chapter_index})"
            )
        owned_gap_keys.add(key)

    for index, item in enumerate(chapters):
        previous_index = next(
            (
                candidate
                for candidate in range(index - 1, -1, -1)
                if chapters[candidate].track is not None
            ),
            None,
        )
        just_played = next(
            (candidate.track for candidate in reversed(chapters[:index]) if candidate.track is not None),
            None,
        )
        previous_music_index = (
            chapters[previous_index].music_index if previous_index is not None else None
        )
        upcoming = next(
            (candidate.track for candidate in chapters[index + 1 :] if candidate.track is not None),
            None,
        )
        upcoming_music_index = next(
            (
                candidate.music_index
                for candidate in chapters[index + 1 :]
                if candidate.track is not None
            ),
            None,
        )
        is_final_chapter = index == len(chapters) - 1
        has_narrative_between_previous_and_current = (
            previous_index is not None
            and any(
                chapters[candidate].track is None
                for candidate in range(previous_index + 1, index)
            )
        )
        chapter_slots: list[NarrationSlotContext] = []

        # The upcoming playable chapter owns a direct A -> B gap.  A
        # narrative-only chapter between them owns the gap instead.
        if (
            item.track is not None
            and item.music_index is not None
            and just_played is not None
            and not has_narrative_between_previous_and_current
        ):
            claim_gap(
                "inter-track",
                previous_music_index,
                item.music_index,
                item.chapter.index,
            )
            chapter_slots.append(
                NarrationSlotContext(
                    slot_id=f"chapter-{item.chapter.index}:before-track",
                    chapter_index=item.chapter.index,
                    placement=NarrationSlotPlacement.BEFORE_TRACK,
                    allowed_block_kinds=[RadioScriptBlockKind.TRACK_INTRO],
                    chapter_track=item.track,
                    just_played_track=just_played,
                    upcoming_track=item.track,
                )
            )

        # The first playable chapter is the immediate playback promise.  When
        # later content exists, it must not also claim the gap after its track:
        # the next playable chapter (or an intervening narrative chapter) owns
        # that physical A -> B gap.  A single-track episode still needs a final
        # OUTRO, so let its first-and-final chapter own the tail instead.
        if item.track is not None and previous_index is None and index == 0:
            if is_final_chapter:
                claim_gap("final", item.music_index, None, item.chapter.index)
                chapter_slots.append(
                    NarrationSlotContext(
                        slot_id=f"chapter-{item.chapter.index}:after-final",
                        chapter_index=item.chapter.index,
                        placement=NarrationSlotPlacement.AFTER_FINAL_TRACK,
                        allowed_block_kinds=[RadioScriptBlockKind.OUTRO],
                        chapter_track=item.track,
                        just_played_track=item.track,
                        upcoming_track=None,
                        is_final=True,
                    )
                )
        elif item.track is not None and is_final_chapter:
            # Only the final chapter owns the tail.
            claim_gap("final", item.music_index, None, item.chapter.index)
            chapter_slots.append(
                NarrationSlotContext(
                    slot_id=f"chapter-{item.chapter.index}:after-final",
                    chapter_index=item.chapter.index,
                    placement=NarrationSlotPlacement.AFTER_FINAL_TRACK,
                    allowed_block_kinds=[RadioScriptBlockKind.OUTRO],
                    chapter_track=item.track,
                    just_played_track=item.track,
                    upcoming_track=None,
                    is_final=True,
                )
            )
        elif item.track is None and just_played is not None:
            if not is_final_chapter and upcoming is None:
                # Several trailing narrative-only chapters would otherwise
                # compete for the same final music tail. Only the last
                # trailing chapter owns that physical slot.
                contexts.append(chapter_slots)
                continue
            claim_gap(
                "final" if is_final_chapter else "inter-track",
                previous_music_index,
                None if is_final_chapter else upcoming_music_index,
                item.chapter.index,
            )
            chapter_slots.append(
                NarrationSlotContext(
                    slot_id=f"chapter-{item.chapter.index}:after-previous",
                    chapter_index=item.chapter.index,
                    placement=(
                        NarrationSlotPlacement.AFTER_FINAL_TRACK
                        if is_final_chapter and upcoming is None
                        else NarrationSlotPlacement.AFTER_TRACK
                    ),
                    allowed_block_kinds=(
                        [RadioScriptBlockKind.OUTRO]
                        if is_final_chapter and upcoming is None
                        else [RadioScriptBlockKind.TRANSITION]
                    ),
                    chapter_track=None,
                    just_played_track=just_played,
                    upcoming_track=upcoming,
                    is_final=is_final_chapter and upcoming is None,
                )
            )
        elif item.track is None and upcoming is not None:
            claim_gap("opening", None, upcoming_music_index, item.chapter.index)
            # Immediate playback starts the first playable track even when
            # leading narrative chapters are trackless.  Those chapters own
            # the opening gap after that music.
            upcoming_position = next(
                position
                for position in range(index + 1, len(chapters))
                if chapters[position].track is not None
            )
            following = next(
                (
                    candidate.track
                    for candidate in chapters[upcoming_position + 1 :]
                    if candidate.track is not None
                ),
                None,
            )
            chapter_slots.append(
                NarrationSlotContext(
                    slot_id=f"chapter-{item.chapter.index}:after-opening",
                    chapter_index=item.chapter.index,
                    placement=NarrationSlotPlacement.AFTER_TRACK,
                    allowed_block_kinds=[
                        RadioScriptBlockKind.INTRO,
                        RadioScriptBlockKind.TRANSITION,
                    ],
                    chapter_track=None,
                    just_played_track=upcoming,
                    upcoming_track=following,
                    is_opening=True,
                )
            )
        contexts.append(chapter_slots)
    return contexts

def _merge_writer_blocks(
    blocks: list[RadioScriptBlock],
    *,
    kind: RadioScriptBlockKind,
) -> RadioScriptBlock | None:
    """Collapse Writer segmentation while preserving application-owned placement."""

    if not blocks:
        return None
    text = " ".join(block.text.strip() for block in blocks)
    if len(text) > 4000:
        raise NarrationPlacementError("merged Writer narration exceeds block text limit")
    tts_text = (
        " ".join((block.tts_text or block.text).strip() for block in blocks)
        if any(block.tts_text is not None for block in blocks)
        else None
    )
    claim_support = [
        support
        for block in blocks
        for support in block.claim_support
    ]
    if len(claim_support) > 8:
        raise NarrationPlacementError("merged Writer narration exceeds claim support limit")
    return blocks[0].model_copy(
        update={
            "kind": kind,
            "text": text,
            "tts_text": tts_text,
            "duration_seconds": min(300, sum(block.duration_seconds for block in blocks)),
            "tts_cues": [cue for block in blocks for cue in block.tts_cues],
            "evidence_ids": [
                evidence_id
                for block in blocks
                for evidence_id in block.evidence_ids
            ],
            "claim_support": claim_support,
            "track_index": None,
        }
    )


def _canonical_slot_blocks(
    blocks: list[RadioScriptBlock],
    contexts: list[NarrationSlotContext],
) -> list[tuple[RadioScriptBlock, NarrationSlotContext]]:
    """Adapt current production slot shapes without inventing a generic solver."""

    if not contexts:
        return []
    if len(contexts) == 1:
        merged = _merge_writer_blocks(
            blocks,
            kind=(
                RadioScriptBlockKind.INTRO
                if contexts[0].is_opening
                else (
                    RadioScriptBlockKind.TRACK_INTRO
                    if contexts[0].placement is NarrationSlotPlacement.BEFORE_TRACK
                    else (
                        RadioScriptBlockKind.OUTRO
                        if contexts[0].placement is NarrationSlotPlacement.AFTER_FINAL_TRACK
                        else RadioScriptBlockKind.TRANSITION
                    )
                )
            ),
        )
        return [(merged, contexts[0])] if merged is not None else []

    if (
        len(contexts) == 2
        and contexts[0].placement is NarrationSlotPlacement.BEFORE_TRACK
        and contexts[1].placement is NarrationSlotPlacement.AFTER_FINAL_TRACK
        and contexts[1].is_final
    ):
        if not blocks:
            return []
        if len(blocks) == 1:
            merged = _merge_writer_blocks(blocks, kind=RadioScriptBlockKind.OUTRO)
            return [(merged, contexts[1])] if merged is not None else []
        before = _merge_writer_blocks([blocks[0]], kind=RadioScriptBlockKind.TRACK_INTRO)
        final = _merge_writer_blocks(blocks[1:], kind=RadioScriptBlockKind.OUTRO)
        assert before is not None and final is not None
        return [(before, contexts[0]), (final, contexts[1])]

    raise NarrationPlacementError("unsupported narration slot shape")


def _assemble_writer_scripts(
    scripts: list[RadioScript | NarrationScript],
    track_count: int,
    *,
    chapter_music_indices: list[int | None],
    slot_contexts: list[list[NarrationSlotContext]],
    chapter_connections: list[EditorialConnection | None] | None = None,
    previous_music_indices: list[int | None] | None = None,
    require_final_slot: bool = True,
) -> tuple[RadioScript, list[WriterChapterDiagnostic]]:
    """Place parsed Writer blocks into deterministic resolved narration slots."""

    if len(scripts) != len(slot_contexts) or len(scripts) != len(chapter_music_indices):
        raise NarrationPlacementError(
            "writer output count does not match the resolved chapter slot count"
        )
    if chapter_connections is not None and len(chapter_connections) != len(scripts):
        raise NarrationPlacementError(
            "chapter connection metadata count does not match writer chapter count"
        )
    chapter_connections = chapter_connections or [None] * len(scripts)
    if previous_music_indices is not None and len(previous_music_indices) != len(scripts):
        raise NarrationPlacementError(
            "previous music metadata count does not match writer chapter count"
        )

    blocks: list[RadioScriptBlock] = []
    diagnostics: list[WriterChapterDiagnostic] = []
    opening_intro_seen = False
    final_outro_seen = False
    final_slot_ids = {
        context.slot_id
        for contexts in slot_contexts
        for context in contexts
        if context.placement is NarrationSlotPlacement.AFTER_FINAL_TRACK
    }
    final_slot_outro_count = 0

    for chapter_index, (script, contexts) in enumerate(zip(scripts, slot_contexts, strict=True)):
        parsed_blocks = _script_blocks(script)
        normalized: list[RadioScriptBlock] = []
        current_music_index = chapter_music_indices[chapter_index]
        previous_music_index = (
            previous_music_indices[chapter_index]
            if previous_music_indices is not None
            else next(
                (
                    chapter_music_indices[prior]
                    for prior in range(chapter_index - 1, -1, -1)
                    if chapter_music_indices[prior] is not None
                ),
                None,
            )
        )
        normalized_slots: list[NarrationSlotContext] = []
        if not contexts and parsed_blocks:
            raise NarrationPlacementError(
                "writer returned narration for a chapter without an owned playback slot "
                f"(chapter={chapter_index})"
            )
        for block, context in _canonical_slot_blocks(parsed_blocks, contexts):
            placed = _place_writer_block_in_slot(
                block,
                context=context,
                current_music_index=current_music_index,
                previous_music_index=previous_music_index,
                opening_intro_seen=opening_intro_seen,
                final_outro_seen=final_outro_seen,
                track_intro_seen=any(
                    item.kind is RadioScriptBlockKind.TRACK_INTRO for item in normalized
                ),
            )
            normalized.append(placed)
            normalized_slots.append(context)
            if placed.kind is RadioScriptBlockKind.INTRO:
                opening_intro_seen = True
            if placed.kind is RadioScriptBlockKind.OUTRO:
                final_outro_seen = True
                if context.slot_id in final_slot_ids:
                    final_slot_outro_count += 1

        diagnostics.append(
            WriterChapterDiagnostic(
                chapter_index=contexts[0].chapter_index if contexts else chapter_index,
                connection_from_previous_track=chapter_connections[chapter_index],
                available_slots=contexts,
                parsed_blocks=parsed_blocks,
                normalized_blocks=normalized,
                normalized_slot_contexts=normalized_slots,
            )
        )
        blocks.extend(normalized)

    if require_final_slot:
        if len(final_slot_ids) != 1:
            raise NarrationPlacementError("expected exactly one final narration slot")
        if final_slot_outro_count != 1:
            raise NarrationPlacementError(
                "final narration slot must return exactly one OUTRO block"
            )
    elif final_slot_ids:
        raise NarrationPlacementError(
            "non-final progressive chunk cannot own the final narration slot"
        )

    return (
        RadioScript(
            blocks=blocks,
            evidence_ids=[
                evidence_id
                for script in scripts
                for evidence_id in _script_evidence_ids(script)
            ],
            intended_duration_seconds=max(
                1, sum(block.intended_duration_seconds for block in blocks)
            ),
        ),
        diagnostics,
    )

def _place_writer_block_in_slot(
    block: RadioScriptBlock,
    *,
    context: NarrationSlotContext,
    current_music_index: int | None,
    previous_music_index: int | None,
    opening_intro_seen: bool,
    final_outro_seen: bool,
    track_intro_seen: bool,
) -> RadioScriptBlock:
    """Convert one Writer block into an application-owned playback anchor."""

    if context.placement is NarrationSlotPlacement.BEFORE_TRACK:
        if current_music_index is None:
            # Leading INTRO is intentionally unindexed: Composer keeps opening
            # music first and places it immediately after that music.
            if block.kind is RadioScriptBlockKind.INTRO:
                return block.model_copy(update={"track_index": None})
            raise NarrationPlacementError(
                f"slot {context.slot_id} cannot place {block.kind.value} before a missing track"
            )
        if block.kind is RadioScriptBlockKind.TRACK_INTRO and not track_intro_seen:
            return block.model_copy(update={"track_index": current_music_index})
        # A duplicate track intro remains audible in the same gap without
        # claiming another before-track anchor.
        if block.kind is RadioScriptBlockKind.TRACK_INTRO:
            raise NarrationPlacementError(
                f"slot {context.slot_id} accepts only one TRACK_INTRO block"
            )
        raise NarrationPlacementError(
            f"slot {context.slot_id} cannot place {block.kind.value} before its track"
        )

    anchor = current_music_index
    if anchor is None:
        anchor = previous_music_index
    if anchor is None and context.is_opening:
        # The first narrative chapter may be trackless, but immediate playback
        # still guarantees that the first resolved music track plays first.
        anchor = 0
    if context.placement in {
        NarrationSlotPlacement.AFTER_TRACK,
        NarrationSlotPlacement.AFTER_FINAL_TRACK,
    } and anchor is None:
        raise NarrationPlacementError(f"slot {context.slot_id} has no playable preceding track")

    if block.kind is RadioScriptBlockKind.INTRO:
        if context.is_opening:
            if opening_intro_seen:
                raise NarrationPlacementError(
                    f"slot {context.slot_id} accepts only one opening INTRO block"
                )
            return block.model_copy(update={"track_index": None})
        return block.model_copy(update={"kind": RadioScriptBlockKind.TRANSITION, "track_index": anchor})
    if block.kind is RadioScriptBlockKind.TRANSITION:
        return block.model_copy(update={"track_index": anchor})
    if block.kind is RadioScriptBlockKind.OUTRO:
        if context.is_final:
            if final_outro_seen:
                raise NarrationPlacementError(
                    "final narration slot returned multiple OUTRO blocks"
                )
            return block.model_copy(update={"track_index": None})
        return block.model_copy(update={"kind": RadioScriptBlockKind.TRANSITION, "track_index": anchor})
    if block.kind is RadioScriptBlockKind.TRACK_INTRO:
        return block.model_copy(update={"kind": RadioScriptBlockKind.TRANSITION, "track_index": anchor})
    raise NarrationPlacementError(f"unsupported Writer block kind: {block.kind.value}")


def _assert_narration_blocks_materialized(
    radio_script: RadioScript,
    playable_episode: PlayableEpisode,
) -> None:
    """Fail explicitly if composition silently drops any generated narration."""

    expected = Counter(block.text for block in radio_script.blocks)
    actual = Counter(
        segment.narration_text
        for segment in playable_episode.segments
        if isinstance(segment, NarrationSegment)
    )
    if expected != actual:
        raise EpisodeAssemblyError(
            "normalized Writer narration does not match final timeline "
            f"(normalized={sum(expected.values())}, timeline={sum(actual.values())})",
            stage="composition",
        )


class StagedProgressiveChapterGenerator:
    """Materialize exactly one normalized session chapter at a time."""

    def __init__(
        self,
        *,
        session: ProgressiveAssemblySession,
        writer: WriterService,
        composer: EpisodeComposer,
        materializer: NarrationMaterializer,
    ) -> None:
        self.session = session
        self.writer = writer
        self.composer = composer
        self.materializer = materializer

    async def generate_next(self, episode: LiveEpisode) -> GeneratedChapter | None:
        chapter = self.session.next_chapter(episode)
        if chapter is None:
            return None
        if not chapter.slot_contexts and chapter.resolved_track is None:
            raise EpisodeAssemblyError(
                "progressive session chapter has no owned narration slot",
                stage="writer_normalization",
                reason_code="slotless_progressive_chapter",
            )

        previous_context = " ".join(
            segment.narration_text
            for segment in episode.ordered_segments
            if isinstance(segment, NarrationSegment) and segment.narration_text
        )[-1000:]
        upcoming = next(
            (
                slot.upcoming_track
                for slot in chapter.slot_contexts
                if slot.upcoming_track is not None
            ),
            None,
        )
        next_track_metadata = (
            f"{upcoming.canonical_artist} - {upcoming.canonical_title}"
            if upcoming is not None
            else ""
        )
        if chapter.slot_contexts:
            try:
                script = await self.writer.write(
                    chapter.chapter,
                    self.session.research.evidence,
                    previous_committed_context=previous_context,
                    next_track_metadata=next_track_metadata,
                    target_duration_seconds=chapter.target_narration_seconds,
                    output_language=self.session.output_language,
                    topic=self.session.topic,
                    slot_contexts=chapter.slot_contexts,
                )
            except ProviderError as error:
                raise EpisodeAssemblyError(str(error), stage="writer") from error
        else:
            script = RadioScript(blocks=[], intended_duration_seconds=1)

        has_persisted_music = any(
            segment.kind is SegmentKind.MUSIC for segment in episode.segments
        )
        try:
            radio_script, _ = _assemble_writer_scripts(
                [script],
                1 if chapter.resolved_track is not None else 0,
                chapter_music_indices=[0 if chapter.resolved_track is not None else None],
                slot_contexts=[chapter.slot_contexts],
                chapter_connections=[chapter.chapter.connection_from_previous_track],
                previous_music_indices=[0 if has_persisted_music else None],
                require_final_slot=(
                    bool(self.session.chapters)
                    and bool(chapter.slot_contexts)
                    and chapter.chapter_id == self.session.chapters[-1].chapter_id
                ),
            )
            prepared_tracks = await self.composer.prepare_tracks(
                [chapter.resolved_track] if chapter.resolved_track is not None else []
            )
            playable = self.composer.compose_prepared(prepared_tracks, radio_script)
            _assert_narration_blocks_materialized(radio_script, playable)
            for segment in playable.segments:
                if isinstance(segment, NarrationSegment):
                    await self.materializer.materialize(segment)
        except EpisodeAssemblyError:
            raise
        except ProviderError as error:
            raise EpisodeAssemblyError(str(error), stage="progressive_chunk") from error
        except NarrationPlacementError as error:
            raise EpisodeAssemblyError(
                str(error),
                stage="writer_normalization",
                reason_code="narration_slot_normalization_failed",
            ) from error
        except (UnresolvedTrackError, ValueError) as error:
            raise EpisodeAssemblyError(str(error), stage="progressive_chunk") from error

        base_order = episode.ordered_segments[-1].order + 1 if episode.ordered_segments else 0
        kind_counts: dict[SegmentKind, int] = {
            SegmentKind.MUSIC: 0,
            SegmentKind.NARRATION: 0,
        }
        segments = []
        for offset, segment in enumerate(playable.segments):
            kind_index = kind_counts[segment.kind]
            kind_counts[segment.kind] += 1
            segments.append(
                segment.model_copy(
                    update={
                        "id": f"{chapter.chapter_id}:{segment.kind.value.lower()}:{kind_index}",
                        "chapter_id": chapter.chapter_id,
                        "order": base_order + offset,
                    }
                )
            )
        return GeneratedChapter(chapter_id=chapter.chapter_id, segments=segments)


def _script_text(script: RadioScript | NarrationScript) -> str:
    return script.text


def _script_blocks(script: RadioScript | NarrationScript) -> list[RadioScriptBlock]:
    if isinstance(script, RadioScript):
        return list(script.blocks)
    return [
        RadioScriptBlock(
            kind=RadioScriptBlockKind.TRANSITION,
            text=script.text,
            tts_text=script.tts_text,
            duration_seconds=script.intended_duration_seconds,
            tts_cues=list(script.tts_cues),
            evidence_ids=list(script.evidence_ids),
        )
    ]


def _assemble_radio_script(
    scripts: list[RadioScript | NarrationScript],
    track_count: int,
    *,
    chapter_music_indices: list[int | None] | None = None,
) -> RadioScript:
    """Place chapter scripts once, preserving chapter order and gap semantics."""
    mapping_available = chapter_music_indices is not None
    chapter_music_indices = (
        chapter_music_indices if chapter_music_indices is not None else list(range(len(scripts)))
    )
    blocks: list[RadioScriptBlock] = []
    opening_intro_seen = False
    track_intro_targets: set[int] = set()
    transition_targets: set[int] = set()
    outro_added = False
    for chapter_index, script in enumerate(scripts):
        chapter_music_index = (
            chapter_music_indices[chapter_index]
            if chapter_index < len(chapter_music_indices)
            else None
        )
        for block in _script_blocks(script):
            if block.kind is RadioScriptBlockKind.INTRO:
                # Only chapter zero owns the episode opening.  A later INTRO
                # is never promoted to that opening gap.  For a trackless beat
                # retain its story as an unindexed transition instead.
                if chapter_index != 0 or opening_intro_seen:
                    if chapter_music_index is None:
                        anchor = _previous_music_index(
                            chapter_index, chapter_music_indices, track_count
                        )
                        blocks.append(
                            block.model_copy(
                                update={
                                    "kind": RadioScriptBlockKind.TRANSITION,
                                    "track_index": anchor,
                                }
                            )
                        )
                    continue
                opening_intro_seen = True
                blocks.append(block.model_copy(update={"track_index": None}))
            elif block.kind is RadioScriptBlockKind.TRACK_INTRO:
                target = _script_track_index(
                    block.track_index, chapter_music_indices, track_count, mapping_available
                ) if block.track_index is not None else chapter_music_index
                if target is None:
                    # A trackless beat still has a spoken story.  Keep it as an
                    # transition in the preceding gap when one exists.  An
                    # explicitly indexed block remains unanchored when its
                    # chapter has no music.
                    anchor = (
                        _previous_music_index(
                            chapter_index, chapter_music_indices, track_count
                        )
                        if block.track_index is None and chapter_music_index is None
                        else None
                    )
                    blocks.append(
                        block.model_copy(
                            update={
                                "kind": RadioScriptBlockKind.TRANSITION,
                                "track_index": anchor,
                            }
                        )
                    )
                    continue
                if target < 0 or target >= track_count or target in track_intro_targets:
                    continue
                if target == 0 and chapter_index != 0:
                    continue
                # The opening track is the immediate playback promise.  If a
                # writer emits both an opening INTRO and TRACK_INTRO(0), keep
                # one spoken block after that music rather than delaying the
                # first playable asset with duplicate narration.
                if target == 0 and opening_intro_seen:
                    continue
                if target == 0:
                    opening_intro_seen = True
                    track_intro_targets.add(target)
                    blocks.append(
                        block.model_copy(
                            update={"kind": RadioScriptBlockKind.INTRO, "track_index": None}
                        )
                    )
                    continue
                track_intro_targets.add(target)
                blocks.append(block.model_copy(update={"track_index": target}))
            elif block.kind is RadioScriptBlockKind.TRANSITION:
                target = _script_track_index(
                    block.track_index, chapter_music_indices, track_count, mapping_available
                ) if block.track_index is not None else chapter_music_index
                if target is None:
                    # Compatibility-form transitions are assigned to gaps by
                    # EpisodeComposer; this also preserves narration-only beats.
                    anchor = (
                        _previous_music_index(
                            chapter_index, chapter_music_indices, track_count
                        )
                        if block.track_index is None and chapter_music_index is None
                        else None
                    )
                    blocks.append(block.model_copy(update={"track_index": anchor}))
                    continue
                narrative_gap = chapter_music_index is None and block.track_index is None
                if target < 0 or target >= track_count - 1 or (
                    target in transition_targets and not narrative_gap
                ):
                    continue
                if not narrative_gap:
                    transition_targets.add(target)
                blocks.append(block.model_copy(update={"track_index": target}))
            elif block.kind is RadioScriptBlockKind.OUTRO:
                if chapter_index != len(scripts) - 1:
                    raise NarrationPlacementError(
                        "OUTRO is only valid in the final narration chapter"
                    )
                if outro_added:
                    raise NarrationPlacementError(
                        "final narration slot returned multiple OUTRO blocks"
                    )
                outro_added = True
                blocks.append(block.model_copy(update={"track_index": None}))

    return RadioScript(
        blocks=blocks,
        evidence_ids=[evidence_id for script in scripts for evidence_id in _script_evidence_ids(script)],
        intended_duration_seconds=max(1, sum(block.intended_duration_seconds for block in blocks)),
    )


def _script_track_index(
    requested_index: int,
    chapter_music_indices: list[int | None],
    track_count: int,
    mapping_available: bool,
) -> int | None:
    """Map Writer chapter indices to final playback track indices safely."""

    if requested_index < 0:
        return None
    if mapping_available and requested_index < len(chapter_music_indices):
        # ``None`` is meaningful: the Writer targeted a narrative-only chapter
        # and must not silently retarget a later playable song.
        return chapter_music_indices[requested_index]
    if mapping_available:
        return None
    if requested_index < len(chapter_music_indices):
        mapped = chapter_music_indices[requested_index]
        if mapped is not None:
            return mapped
    return requested_index if requested_index < track_count else None


def _previous_music_index(
    chapter_index: int, chapter_music_indices: list[int | None], track_count: int
) -> int | None:
    """Return the nearest playable track before a narrative-only chapter.

    The final music track is a valid anchor here: a trailing narrative beat
    belongs after that track, whereas ordinary indexed transitions still use
    their separate gap validation above.
    """
    for index in range(min(chapter_index - 1, len(chapter_music_indices) - 1), -1, -1):
        music_index = chapter_music_indices[index]
        if music_index is not None and 0 <= music_index < track_count:
            return music_index
    return None


def _script_evidence_ids(script: RadioScript | NarrationScript) -> list[str]:
    if isinstance(script, RadioScript):
        return list(script.evidence_ids) + [evidence_id for block in script.blocks for evidence_id in block.evidence_ids]
    return list(script.evidence_ids)


def _duration_summary(episode: PlayableEpisode) -> AssemblyDurationSummary:
    music_seconds = sum(
        segment.duration_seconds
        for segment in episode.segments
        if segment.kind is SegmentKind.MUSIC
    )
    narration_seconds = sum(
        segment.duration_seconds
        for segment in episode.segments
        if segment.kind is SegmentKind.NARRATION
    )
    total = music_seconds + narration_seconds
    return AssemblyDurationSummary(
        music_seconds=music_seconds,
        narration_seconds=narration_seconds,
        total_seconds=total,
        narration_ratio=(narration_seconds / total) if total else 0.0,
    )


def _mock_writer_chapter_index(prompt: str) -> int:
    marker = "Chapter: "
    if marker not in prompt:
        return 0
    serialized = prompt.split(marker, 1)[1].split("\nEvidence:", 1)[0]
    try:
        value = json.loads(serialized).get("index", 0)
    except (TypeError, ValueError):
        return 0
    return value if isinstance(value, int) and value >= 0 else 0


def _mock_next_track_metadata(prompt: str) -> str:
    marker = "Next track metadata: "
    if marker not in prompt:
        return ""
    return prompt.split(marker, 1)[1].split("\nHost style:", 1)[0].strip()


def _mock_chapter_has_no_track(prompt: str) -> bool:
    marker = "Chapter: "
    if marker not in prompt:
        return False
    serialized = prompt.split(marker, 1)[1].split("\nEvidence:", 1)[0]
    try:
        return json.loads(serialized).get("track") is None
    except (TypeError, ValueError):
        return False


def _mock_writer_slot_contexts(prompt: str) -> list[dict[str, object]]:
    marker = "Narration slot contexts: "
    if marker not in prompt:
        return []
    serialized = prompt.split(marker, 1)[1].split(
        "\nThe following legacy field", 1
    )[0]
    try:
        value = json.loads(serialized)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


class MockEpisodeAssemblyLLM(ProgressiveLLMProvider):
    """Deterministic structured provider used by the zero-credential factory."""

    _tracks = (
        ("Mira Fields", "Neon First Light", NoveltyDistance.VERY_CLOSE),
        ("Signal Garden", "Midnight Transfer", NoveltyDistance.CLOSE),
        ("Southbound FM", "Daybreak in Stereo", NoveltyDistance.BRIDGE),
        ("Southbound FM", "Afterimage Avenue", NoveltyDistance.DISCOVERY),
    )

    async def structured(
        self,
        prompt: str,
        output_type: type[BaseModel],
        *,
        transport: StructuredTransport,
        profile: InferenceProfile,
        stage: str | None = None,
    ) -> BaseModel:
        del transport, profile, stage
        if output_type is FastStartPlan:
            proposals = [self._proposal(item) for item in self._tracks]
            return FastStartPlan(
                anchor_understanding=["Start with a bright, nocturnal synth texture."],
                immediate_taste_hypotheses=[],
                next_candidates=proposals[:2],
                selected_next_track=proposals[0],
                first_narration=NarrationScript(
                    text="从熟悉的夜色律动出发，我们先听见第一束光，再把路径慢慢打开。",
                    intended_duration_seconds=8,
                ),
                research_plan=generic_research_plan(
                    FastResearchInput(topic="guided listening", desired_duration_seconds=900)
                ),
            )
        if output_type is ResearchPlan:
            return ResearchPlan(
                central_question="What evidence explains this guided listening request?",
                facets=[
                    ResearchFacet(
                        id="context",
                        label="Context",
                        question="What context connects the selected tracks?",
                        priority=80,
                        source_preferences=["reference"],
                    )
                ],
                background_queries=[],
            )
        if output_type is ProgramSkeleton:
            chapters = [
                ChapterPlan(
                    index=index,
                    track=self._proposal(item),
                    narrative_role=(
                        NarrativeRole.ANCHOR
                        if index == 0
                        else NarrativeRole.RESOLUTION
                        if index == len(self._tracks) - 1
                        else NarrativeRole.BRIDGE
                    ),
                    reason="Follow the shared texture while opening a new scene.",
                    novelty_distance=item[2],
                    narration_goal="Explain the sonic connection in one concise radio block.",
                )
                for index, item in enumerate(self._tracks)
            ]
            return ProgramSkeleton(
                thesis="A deterministic mock arc from familiar texture to wider discovery.",
                chapters=chapters,
                estimated_duration_seconds=900,
            )
        if output_type is RadioScript:
            index = _mock_writer_chapter_index(prompt)
            contexts = _mock_writer_slot_contexts(prompt)
            if not contexts:
                return RadioScript(blocks=[], intended_duration_seconds=1)
            blocks: list[RadioScriptBlock] = []
            for context in contexts:
                allowed_value = context.get("allowed_block_kinds", [])
                allowed = (
                    {item for item in allowed_value if isinstance(item, str)}
                    if isinstance(allowed_value, list)
                    else set()
                )
                if "track_intro" in allowed:
                    kind = RadioScriptBlockKind.TRACK_INTRO
                    text = f"\u73b0\u5728\u8fdb\u5165\u7b2c {index + 1} \u9996\u3002"
                    duration = 4
                elif "outro" in allowed:
                    kind = RadioScriptBlockKind.OUTRO
                    text = "This route comes to a close here."
                    duration = 5
                elif "intro" in allowed and index == 0:
                    kind = RadioScriptBlockKind.INTRO
                    text = "\u6b22\u8fce\u6765\u5230\u4eca\u665a\u7684\u542c\u6b4c\u8def\u7ebf\u3002"
                    duration = 5
                elif "transition" in allowed:
                    kind = RadioScriptBlockKind.TRANSITION
                    text = (
                        f"\u73b0\u5728\u8fdb\u5165\u7b2c {index + 1} \u9996\u3002"
                        if _mock_chapter_has_no_track(prompt)
                        else "\u63a5\u4e0b\u6765\uff0c\u6211\u4eec\u628a\u955c\u5934\u63a8\u5411\u66f4\u8fdc\u7684\u5730\u65b9\u3002"
                    )
                    duration = 4
                else:
                    continue
                blocks.append(
                    RadioScriptBlock(kind=kind, text=text, duration_seconds=duration)
                )
            return RadioScript(
                blocks=blocks,
                intended_duration_seconds=max(1, sum(block.duration_seconds for block in blocks)),
            )
        raise TypeError(f"mock assembly provider does not support {output_type.__name__}")

    @staticmethod
    def _proposal(item: tuple[str, str, NoveltyDistance]) -> TrackProposal:
        artist, title, distance = item
        return TrackProposal(
            artist=artist,
            title=title,
            reasons=["deterministic mock catalog fixture"],
            similarity_dimensions=["groove", "texture"],
            confidence=0.9,
            novelty_distance=distance,
        )



def create_episode_assembly_service(
    settings: ProviderSettings | None = None,
    *,
    storage: ObjectStorageProvider | None = None,
) -> LiveEpisodeAssemblyService:
    """Create one assembly path whose provider capabilities can be gated independently."""
    settings = settings or ProviderSettings.from_env()
    ledger = UsageLedger()
    music_registry = build_music_registry(settings)
    storage = storage or LocalObjectStorageProvider()
    live_settings = settings.for_live_capability()
    mock_llm = MockEpisodeAssemblyLLM()

    fast_llm: ProgressiveLLMProvider = (
        mock_llm
        if settings.resolved_fast_start_provider == "mock"
        else DeepSeekLLMProvider(live_settings, ledger=ledger)
    )
    research_llm: ProgressiveLLMProvider = (
        mock_llm
        if settings.resolved_research_provider == "mock"
        else DeepSeekLLMProvider(live_settings, ledger=ledger)
    )
    curator_llm: ProgressiveLLMProvider = (
        mock_llm
        if settings.resolved_curator_provider == "mock"
        else DeepSeekLLMProvider(live_settings, ledger=ledger)
    )
    writer_llm: ProgressiveLLMProvider = (
        mock_llm
        if settings.resolved_writer_provider == "mock"
        else DeepSeekLLMProvider(live_settings, ledger=ledger)
    )

    if settings.resolved_research_provider == "mock":
        discovery: SearchProvider = FakeSearchProvider()
        research: SearchProvider = FakeSearchProvider()
    else:
        discovery = ExaSearchProvider(live_settings, ledger=ledger)
        research = TavilySearchProvider(live_settings, ledger=ledger)

    tts: TTSProvider = (
        MockTTSProvider(storage)
        if settings.resolved_tts_provider == "mock"
        else MiniMaxTTSProvider(live_settings, storage=storage, ledger=ledger)
    )

    fast_research = FastResearchService(discovery=discovery, research=research, ledger=ledger)
    background_research = BackgroundResearchService(
        discovery=discovery,
        research=research,
        ledger=ledger,
        planner=BackgroundResearchPlanner(research_llm),
    )
    fast_path = FastPathCoordinator(
        research=fast_research,
        planner=FastStartPlanner(fast_llm),
    )
    background_pipeline = BackgroundIntelligencePipeline(
        research=background_research,
        curator=CuratorService(curator_llm),
        writer=WriterService(writer_llm),
    )
    return LiveEpisodeAssemblyService(
        fast_path=fast_path,
        background_pipeline=background_pipeline,
        retrieval=MusicRetrievalService(music_registry),
        composer=EpisodeComposer(music_registry),
        materializer=NarrationMaterializer(tts, storage),
        ledger=ledger,
    )
