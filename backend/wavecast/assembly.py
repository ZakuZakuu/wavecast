"""Application-level assembly of a bounded, playable WaveCast episode.

The runtime and the intelligence services remain separate: this module is the
thin application seam that joins their provider-neutral contracts.  It never
promotes a proposal directly into playback; every chapter crosses the
deterministic catalog-resolution boundary first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from uuid import uuid4

from pydantic import BaseModel, Field

from wavecast.catalog_pool import (
    AvailabilityStatus,
    CatalogPool,
    CatalogPoolBuilder,
    PoolBuildConfig,
)
from wavecast.composer import EpisodeComposer, PreparedMusicAsset
from wavecast.coverage import (
    candidate_artist_names,
    covered_artists,
    ensure_required_coverage,
    unfulfilled_artists,
)
from wavecast.intelligence.background import BackgroundIntelligencePipeline
from wavecast.intelligence.curation import CuratorContractError, CuratorService
from wavecast.intelligence.fast_start import FastPathCoordinator, FastPathResult, FastStartPlanner
from wavecast.intelligence.models import (
    ChapterPlan,
    EditorialConnection,
    Evidence,
    FastResearchInput,
    FastResearchResult,
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
from wavecast.models.episode import (
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    PlayableEpisode,
    SegmentKind,
    SegmentState,
)
from wavecast.narration_quality import opener_of
from wavecast.orchestration.generation import GeneratedChapter
from wavecast.orchestration.staged import (
    ProgressiveAssemblyChapter,
    ProgressiveAssemblySession,
    ProgressiveSessionDiagnostic,
)
from wavecast.presentation import (
    HostMode,
    PresentationIntent,
    narration_ratio_for_host_mode,
)
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import (
    AudioAsset,
    AudioAssetType,
    ObjectStorageProvider,
    ProgressiveLLMProvider,
    SearchProvider,
    TTSProvider,
)
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import (
    ProviderConfigurationError,
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
from wavecast.providers.usage import (
    UsageLedger,
    UsageTotals,
    scoped_to_episode,
    usage_diagnostics,
)
from wavecast.route_consistency import (
    foreign_artists,
    known_artist_names,
    track_true_chapter,
    used_an_alternate,
)
from wavecast.route_duration import (
    is_underfilled,
    last_track_to_keep,
    music_budget_seconds,
    track_seconds,
)
from wavecast.stations import StationId
from wavecast.storage.assets import LocalObjectStorageProvider
from wavecast.text_identity import canonical_name, song_title_key, strip_latin_accents
from wavecast.timing import (
    ProgramTimingPlan,
    ProgramTimingSummary,
    build_program_timing_plan,
    summarize_program_timing,
)

logger = logging.getLogger(__name__)


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
    max_tracks: int = Field(default=4, ge=2, le=16)
    max_chapters: int = Field(default=16, ge=2, le=32)
    listener_taste_context: str | None = Field(default=None, max_length=1000)
    presentation_intent: PresentationIntent = Field(default_factory=PresentationIntent)
    output_language: OutputLanguage = OutputLanguage.AUTO
    station: StationId | None = None
    required_artists: list[str] = Field(default_factory=list, max_length=4)
    # Seeds the variety of choices (which tracks the Curator sees first); the programme's id.
    variety_seed: str = Field(default="", max_length=120)


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
    catalog_pool: CatalogPool | None = None
    unfulfilled_artists: tuple[str, ...] = ()


_ESTIMATED_TRACK_DURATION_SECONDS = 180
_MIN_PROGRESSIVE_DURATION_COVERAGE_NUMERATOR = 3
_MIN_PROGRESSIVE_DURATION_COVERAGE_DENOMINATOR = 4
_CATALOG_REPLACEMENT_LIMIT = 3


def _required_progressive_music_seconds(
    request: LiveEpisodeAssemblyRequest,
    narration_ratio: float,
) -> int:
    target_narration_ratio = narration_ratio_for_host_mode(
        request.presentation_intent.host_mode,
        full_ratio=narration_ratio,
    )
    requested_music_seconds = int(
        request.desired_duration_seconds * (1.0 - target_narration_ratio)
    )
    # The floor below which a route is refused stays tied to the fixed route size even when
    # duration scaling raises the track cap: a longer request may add tracks when the catalog
    # has them, but a catalog with fewer playable tracks must yield a shorter programme, not
    # a failed one.
    bounded_music_target_seconds = min(
        requested_music_seconds,
        min(request.max_tracks, _FIXED_ROUTE_LIMITS[0]) * _ESTIMATED_TRACK_DURATION_SECONDS,
    )
    return (
        bounded_music_target_seconds * _MIN_PROGRESSIVE_DURATION_COVERAGE_NUMERATOR
        + _MIN_PROGRESSIVE_DURATION_COVERAGE_DENOMINATOR
        - 1
    ) // _MIN_PROGRESSIVE_DURATION_COVERAGE_DENOMINATOR

def _route_underfilled(
    request: LiveEpisodeAssemblyRequest,
    narration_ratio: float,
    route: Sequence[_ResolvedChapter],
) -> bool:
    """True when the route's music is clearly shorter than the programme's music budget.

    Uses the lengths the catalog reported (a typical song's when it did not), so a route of
    seven-minute tracks is not asked for as many songs as one of three-minute tracks.
    """

    budget = music_budget_seconds(
        request.desired_duration_seconds,
        narration_ratio_for_host_mode(
            request.presentation_intent.host_mode, full_ratio=narration_ratio
        ),
    )
    return is_underfilled(
        [item.track.duration_seconds for item in route if item.track is not None], budget
    )


def _fit_route_to_time_budget(
    route: list[_ResolvedChapter],
    *,
    request: LiveEpisodeAssemblyRequest,
    narration_ratio: float,
    keep_at_least: int,
) -> list[_ResolvedChapter]:
    """End the route on the track whose running total lands closest to the time budget.

    The opening and the locked successor are never dropped.  Everything after the chosen
    track is speculative future that was never played, so it is simply not part of the
    programme; the last kept chapter closes it.
    """

    budget = music_budget_seconds(
        request.desired_duration_seconds,
        narration_ratio_for_host_mode(
            request.presentation_intent.host_mode, full_ratio=narration_ratio
        ),
    )
    music = [(index, item.track) for index, item in enumerate(route) if item.track is not None]
    if len(music) <= keep_at_least:
        return route
    last = last_track_to_keep(
        [track.duration_seconds for _index, track in music],
        budget,
        keep_at_least=keep_at_least,
    )
    if last == len(music) - 1:
        return route
    kept = route[: music[last][0] + 1]
    closing = kept[-1]
    kept[-1] = replace(
        closing,
        chapter=closing.chapter.model_copy(update={"narrative_role": NarrativeRole.RESOLUTION}),
        writer_chapter=closing.writer_chapter.model_copy(
            update={"narrative_role": NarrativeRole.RESOLUTION}
        ),
    )
    logger.info(
        "route_fitted budget_s=%d kept_tracks=%d dropped_tracks=%d",
        budget,
        last + 1,
        len(music) - last - 1,
    )
    return kept


_NOVELTY_RANK = {
    NoveltyDistance.VERY_CLOSE: 0,
    NoveltyDistance.CLOSE: 1,
    NoveltyDistance.BRIDGE: 2,
    NoveltyDistance.DISCOVERY: 3,
    NoveltyDistance.SURPRISE: 4,
}


_POOL_PROPOSAL_LIMIT = 12

# Fixed route size used before duration scaling (kept as the default behaviour).
_FIXED_ROUTE_LIMITS = (5, 8)
# Typical length of a song in the catalog and the music share of a light-hosted programme.
_SCALED_TRACK_SECONDS = 190
_SCALED_MUSIC_SHARE = 0.9
_SCALED_MIN_TRACKS = 3
_SCALED_MAX_TRACKS = 16
_SCALED_MAX_CHAPTERS = 32


def route_limits_for_duration(desired_seconds: int, *, scaled: bool) -> tuple[int, int]:
    """``(max_tracks, max_chapters)`` for a programme of the requested length.

    Unscaled, a fixed route of 5 tracks / 8 chapters capped every programme near 18
    minutes whatever length the listener chose.  Scaled, the cap follows the request:
    enough tracks to fill the music share at a typical song length, plus room for the
    narrative-only beats, within the schema ceilings.  The actual length still depends on
    how many playable tracks the catalog offers.
    """

    if not scaled:
        return _FIXED_ROUTE_LIMITS
    tracks = -(-int(desired_seconds * _SCALED_MUSIC_SHARE) // _SCALED_TRACK_SECONDS)
    tracks = max(_SCALED_MIN_TRACKS, min(_SCALED_MAX_TRACKS, tracks))
    chapters = min(_SCALED_MAX_CHAPTERS, tracks + max(3, tracks // 2))
    return tracks, chapters


def _pool_proposals(fast_plan: FastStartPlan, bundle: ResearchBundle) -> list[TrackProposal]:
    """LLM-named tracks worth verifying: FastStart's route first, then research candidates."""

    ordered: list[TrackProposal] = []
    if fast_plan.selected_next_track is not None:
        ordered.append(fast_plan.selected_next_track)
    ordered.extend(fast_plan.next_candidates)
    ordered.extend(bundle.candidates)
    seen: set[tuple[str, str]] = set()
    unique: list[TrackProposal] = []
    for proposal in ordered:
        key = _proposal_identity_key(proposal)
        if key in seen:
            continue
        seen.add(key)
        unique.append(proposal)
    return unique[:_POOL_PROPOSAL_LIMIT]


_POOL_ARTIST_LIMIT = 3
_POOL_TOPIC_ARTIST_LIMIT = 2
_COVERAGE_POOL_CONFIG = PoolBuildConfig(max_verifications=8, timeout_seconds=15.0)
# Same bounds the factory gives the pool when its flag is on.
_NAMED_ARTIST_POOL_CONFIG = PoolBuildConfig(timeout_seconds=30.0)


def _pool_artist_queries(
    proposals: Sequence[TrackProposal],
    required: Sequence[str] = (),
    topic: str = "",
) -> list[str]:
    """Distinct artists to search: the ones the request names, then the model's, in order.

    Artists the listener named come first and are never cut: the route has to play them.
    An artist whose own catalog is mostly unplayable (licensing) still leads to related
    playable music through the artists the model associates with the topic; the pool caps
    how many tracks any one artist can contribute.  Name-like phrases in the request itself
    are searched too, so an artist the model forgot to propose can still be found.
    """

    artists: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> bool:
        key = canonical_name(name)
        if not key or key in seen:
            return False
        seen.add(key)
        artists.append(name)
        return True

    for name in required:
        add(name)
    proposed = 0
    for proposal in proposals:
        if proposed >= _POOL_ARTIST_LIMIT:
            break
        if add(proposal.artist):
            proposed += 1
    added = 0
    for name in candidate_artist_names(topic, limit=_POOL_TOPIC_ARTIST_LIMIT + len(required)):
        if added >= _POOL_TOPIC_ARTIST_LIMIT:
            break
        if add(name):
            added += 1
    return artists


def _proposal_identity_key(proposal: TrackProposal) -> tuple[str, str]:
    return (
        canonical_name(proposal.artist),
        canonical_name(proposal.title),
    )


def _catalog_replacement_pool(
    chapter: ChapterPlan,
    bundle: ResearchBundle,
    fast_plan: FastStartPlan,
    attempted: set[tuple[str, str]],
) -> list[TrackProposal]:
    """Rank already-researched candidates for one unresolved editorial slot."""

    pool: list[TrackProposal] = []
    if fast_plan.selected_next_track is not None:
        pool.append(fast_plan.selected_next_track)
    pool.extend(fast_plan.next_candidates)
    pool.extend(bundle.candidates)

    target_rank = (
        _NOVELTY_RANK[chapter.novelty_distance]
        if chapter.novelty_distance is not None
        else None
    )
    chapter_evidence = set(chapter.evidence_ids)
    scored: list[tuple[int, int, float, tuple[str, str], TrackProposal]] = []
    seen = set(attempted)
    for proposal in pool:
        key = _proposal_identity_key(proposal)
        if key in seen:
            continue
        seen.add(key)
        distance = (
            abs(_NOVELTY_RANK[proposal.novelty_distance] - target_rank)
            if target_rank is not None
            else 0
        )
        # A replacement is still the same editorial slot, so do not jump more
        # than one novelty step merely to make catalog resolution succeed.
        if distance > 1:
            continue
        evidence_overlap = len(chapter_evidence.intersection(proposal.evidence_ids))
        scored.append(
            (
                distance,
                -evidence_overlap,
                -proposal.confidence,
                key,
                proposal,
            )
        )
    scored.sort(key=lambda item: item[:4])
    return [item[4] for item in scored[:_CATALOG_REPLACEMENT_LIMIT]]


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
        catalog_pool_builder: CatalogPoolBuilder | None = None,
        duration_scaling: bool = False,
    ) -> None:
        self.catalog_pool_builder = catalog_pool_builder
        self.duration_scaling = duration_scaling
        self.fast_path = fast_path
        self.background_pipeline = background_pipeline
        self.retrieval = retrieval
        self.composer = composer
        self.materializer = materializer
        self.ledger = ledger or UsageLedger()
        if not 0.1 <= narration_ratio <= 0.2:
            raise ValueError("narration_ratio must be between 0.1 and 0.2")
        self.narration_ratio = narration_ratio

    async def prepare_fast_successor(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        opening_track: ResolvedTrack,
        request_id: str | None = None,
    ) -> GeneratedChapter | None:
        """Prepare one exact, playable successor from FastStart only.

        This is the continuity bootstrap seam: it stops before background
        research, Curator, Writer, and TTS so the Episode can persist a real
        ready successor while the fuller route is still being planned.
        """

        intelligence_input = FastResearchInput(
            topic=request.topic,
            anchor_tracks=list(request.anchor_tracks),
            desired_duration_seconds=request.desired_duration_seconds,
            listener_taste_context=request.listener_taste_context,
            output_language=request.output_language,
        )
        try:
            fast_result = await self.fast_path.run(
                intelligence_input,
                request_id=request_id or uuid4().hex,
            )
        except ProviderError:
            return None

        proposals: list[TrackProposal] = []
        if fast_result.plan.selected_next_track is not None:
            proposals.append(fast_result.plan.selected_next_track)
        proposals.extend(fast_result.plan.next_candidates)

        seen: set[tuple[str, str]] = set()

        async def prepare_candidate(
            proposal: TrackProposal,
        ) -> GeneratedChapter | None:
            proposal_key = (canonical_name(proposal.artist), canonical_name(proposal.title))
            if proposal_key in seen:
                return None
            seen.add(proposal_key)
            try:
                resolved = await resolve_track_proposal_across_providers(
                    self.retrieval,
                    proposal,
                )
            except ProviderError:
                return None
            if resolved is None or _same_song_identity(resolved, opening_track):
                return None

            # FastStart owns continuity, not final host copy. Persist music
            # immediately and let the evidence-scoped Writer author the first
            # A -> B bridge asynchronously once the progressive session exists.
            # This removes the repeated deterministic "that was / up next"
            # sentence from normal listening without putting Writer on the
            # time-to-first-successor critical path.
            bootstrap_script = RadioScript(blocks=[], intended_duration_seconds=1)

            try:
                prepared = await self.composer.prepare_tracks([resolved])
                playable = self.composer.compose_prepared(
                    prepared,
                    bootstrap_script,
                )
            except (ProviderError, UnresolvedTrackError, ValueError):
                return None

            music = [
                segment
                for segment in playable.segments
                if isinstance(segment, MusicSegment)
            ]
            narration = [
                segment
                for segment in playable.segments
                if isinstance(segment, NarrationSegment)
            ]
            if (
                len(music) != 1
                or not music[0].is_audio_ready
                or narration
            ):
                return None
            segments: list[MusicSegment | NarrationSegment] = []
            if request.presentation_intent.host_mode is not HostMode.NONE:
                segments.append(
                    _pending_narration_placeholder(
                        "chapter-2",
                        planned_duration_seconds=1,
                    )
                )
            segments.extend(music)
            return _generated_runtime_chapter(
                "chapter-2",
                segments,
                base_order=1,
            )

        # Prefer the actual FastStart route when it produced a usable exact
        # catalog identity.
        for proposal in proposals:
            prepared = await prepare_candidate(proposal)
            if prepared is not None:
                return prepared

        # Only if FastStart cannot yield a playable successor, spend one bounded
        # catalog lookup on another song by the opening artist. This keeps a
        # concrete next source ahead of the slower Research/Curator route.
        catalog_fallbacks = await self.retrieval.search(
            opening_track.canonical_artist,
            requested_artist=opening_track.canonical_artist,
            limit=5,
        )
        for candidate in catalog_fallbacks:
            prepared = await prepare_candidate(
                TrackProposal(
                    artist=candidate.artist,
                    title=candidate.title,
                    reasons=["FastStart catalog bootstrap from the opening artist."],
                    confidence=0.5,
                )
            )
            if prepared is not None:
                return prepared
        return None

    async def prepare_progressive_session(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        opening_track: ResolvedTrack,
        locked_successor: ResolvedTrack | None = None,
        request_id: str | None = None,
    ) -> ProgressiveAssemblySession:
        """Prepare serializable intelligence without producing future audio.

        The opening identity is application-owned and explicit. This seam ends
        before Writer, composition, TTS, and playback-asset preparation.
        """

        prepared = await self._prepare_intelligence(
            request,
            request_id=request_id,
            locked_successor=locked_successor,
            reserved_tracks=(opening_track,),
        )
        return _build_progressive_session(
            request=request,
            prepared=prepared,
            opening_track=opening_track,
            locked_successor=locked_successor,
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

    async def _resolve_catalog_replacement(
        self,
        chapter: ChapterPlan,
        bundle: ResearchBundle,
        fast_plan: FastStartPlan,
        *,
        attempted: set[tuple[str, str]],
        used_tracks: list[ResolvedTrack],
    ) -> tuple[ResolvedTrack, TrackProposal, str] | None:
        """Recover one unresolved speculative slot without weakening identity safety."""

        for proposal in _catalog_replacement_pool(
            chapter,
            bundle,
            fast_plan,
            attempted,
        ):
            try:
                candidate = await resolve_track_proposal_across_providers(
                    self.retrieval,
                    proposal,
                )
            except ProviderError:
                continue
            if candidate is None or any(
                _same_song_identity(candidate, used) for used in used_tracks
            ):
                continue
            return candidate, proposal, "researched_candidate"

        # Final bounded recovery: keep the Curator-selected artist but use a
        # different real playable song from that exact artist. The replacement
        # receives its own canonical title and generic narration metadata; it is
        # never treated as the unresolved original song.
        artists: list[str] = []
        artist_proposals: list[TrackProposal] = []
        if chapter.track is not None:
            artist_proposals.append(chapter.track)
        artist_proposals.extend(chapter.track_alternates)
        for candidate_proposal in artist_proposals:
            normalized = canonical_name(candidate_proposal.artist)
            if normalized and normalized not in {
                canonical_name(item) for item in artists
            }:
                artists.append(candidate_proposal.artist)
        for artist in artists[:_CATALOG_REPLACEMENT_LIMIT]:
            try:
                alternatives = await self.retrieval.search(
                    artist,
                    requested_artist=artist,
                    limit=5,
                )
            except ProviderError:
                continue
            artist_key = canonical_name(artist)
            for alternative in alternatives:
                if not alternative.playable:
                    continue
                if canonical_name(alternative.artist) != artist_key:
                    continue
                candidate = ResolvedTrack(
                    track_ref=alternative.track_ref,
                    canonical_artist=alternative.artist,
                    canonical_title=alternative.title,
                    duration_seconds=alternative.duration_seconds or None,
                )
                if any(_same_song_identity(candidate, used) for used in used_tracks):
                    continue
                proposal = TrackProposal(
                    artist=alternative.artist,
                    title=alternative.title,
                    reasons=[
                        "Catalog-aware replacement for an unresolved editorial slot."
                    ],
                    similarity_dimensions=(
                        list(chapter.track.similarity_dimensions)
                        if chapter.track is not None
                        else []
                    ),
                    confidence=0.5,
                    novelty_distance=(
                        chapter.novelty_distance
                        or (
                            chapter.track.novelty_distance
                            if chapter.track is not None
                            else NoveltyDistance.CLOSE
                        )
                    ),
                )
                return candidate, proposal, "same_artist_catalog"
        return None

    async def _extend_underfilled_route_with_curator(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        bundle: ResearchBundle,
        fast_plan: FastStartPlan,
        opening_track: ResolvedTrack,
        locked_successor: ResolvedTrack,
        resolved_chapters: list[_ResolvedChapter],
        used_tracks: list[ResolvedTrack],
        trace: GenerationTrace,
        catalog_pool: CatalogPool | None = None,
    ) -> tuple[list[_ResolvedChapter], list[UnresolvedAssemblyProposal]]:
        """Ask Curator once for topic-driven continuation before emergency catalog fill."""

        normalized = _normalize_progressive_route(
            request=request,
            resolved_chapters=resolved_chapters,
            opening_track=opening_track,
            locked_successor=locked_successor,
        )
        current_track_count = sum(item.track is not None for item in normalized)
        if (
            not _route_underfilled(request, self.narration_ratio, normalized)
            or current_track_count >= request.max_tracks
            or len(normalized) >= request.max_chapters
        ):
            return resolved_chapters, []

        if not any(
            _same_song_identity(locked_successor, item)
            for item in used_tracks
        ):
            used_tracks.append(locked_successor)

        committed: list[ChapterPlan] = []
        for item in normalized:
            if item.track is None:
                continue
            proposal = TrackProposal(
                artist=item.track.canonical_artist,
                title=item.track.canonical_title,
                reasons=["Already committed playable programme route."],
                similarity_dimensions=(
                    list(item.chapter.track.similarity_dimensions)
                    if item.chapter.track is not None
                    else []
                ),
                evidence_ids=list(item.chapter.evidence_ids),
                confidence=1.0,
                novelty_distance=(
                    item.chapter.novelty_distance or NoveltyDistance.CLOSE
                ),
            )
            committed.append(
                item.writer_chapter.model_copy(
                    update={
                        "index": len(committed),
                        "track": proposal,
                        "track_alternates": [],
                    }
                )
            )

        trace.mark(
            "curator_continuation_started",
            committed_track_count=len(committed),
        )
        try:
            continuation = await self.background_pipeline.curator.curate(
                bundle,
                fast_plan,
                desired_duration_seconds=request.desired_duration_seconds,
                max_tracks=request.max_tracks,
                max_chapters=request.max_chapters,
                committed_chapters=committed,
                output_language=resolve_output_language(
                    request.output_language,
                    request.topic,
                ),
                topic=request.topic,
                trace=trace,
                catalog_pool=catalog_pool,
                required_artists=request.required_artists,
                variety_seed=request.variety_seed,
            )
        except (CuratorContractError, ProviderError) as error:
            trace.mark(
                "curator_continuation_failed",
                error_type=type(error).__name__,
            )
            return resolved_chapters, []

        additions = [
            chapter
            for chapter in continuation.chapters
            if chapter.index >= len(committed)
        ]
        if not additions:
            trace.mark("curator_continuation_empty")
            return resolved_chapters, []

        continuation_unresolved: list[UnresolvedAssemblyProposal] = []
        added_count = 0
        for continuation_chapter in additions:
            normalized_now = _normalize_progressive_route(
                request=request,
                resolved_chapters=resolved_chapters,
                opening_track=opening_track,
                locked_successor=locked_successor,
            )
            if not _route_underfilled(request, self.narration_ratio, normalized_now):
                break

            chapter = continuation_chapter.model_copy(
                update={"index": len(resolved_chapters)}
            )
            resolved: ResolvedTrack | None = None
            selected_proposal: TrackProposal | None = None
            replacement_kind: str | None = None
            if chapter.track is not None:
                candidates = [chapter.track, *chapter.track_alternates]
                attempted = {_proposal_identity_key(item) for item in candidates}
                last_resolution_reason = "no exact playable catalog match"
                for candidate_rank, proposal in enumerate(candidates):
                    try:
                        candidate = await self._resolve_proposal_track(proposal, catalog_pool)
                    except ProviderError as error:
                        candidate = None
                        last_resolution_reason = (
                            f"resolution provider failed: {type(error).__name__}"
                        )
                    if candidate is None:
                        continue
                    if any(
                        _same_song_identity(candidate, used)
                        for used in used_tracks
                    ):
                        last_resolution_reason = "duplicate episode song identity"
                        continue
                    resolved = candidate
                    selected_proposal = proposal
                    used_tracks.append(candidate)
                    if candidate_rank > 0:
                        trace.mark(
                            "curator_continuation_alternate_resolved",
                            candidate_rank=candidate_rank + 1,
                        )
                    break

                if resolved is None:
                    replacement = await self._resolve_catalog_replacement(
                        chapter,
                        bundle,
                        fast_plan,
                        attempted=attempted,
                        used_tracks=used_tracks,
                    )
                    if replacement is not None:
                        resolved, selected_proposal, replacement_kind = replacement
                        used_tracks.append(resolved)
                    else:
                        continuation_unresolved.append(
                            UnresolvedAssemblyProposal(
                                chapter_index=chapter.index,
                                proposal=chapter.track,
                                reason=last_resolution_reason,
                            )
                        )

            route_chapter = chapter
            if replacement_kind is not None and selected_proposal is not None:
                route_chapter = chapter.model_copy(
                    update={
                        "track": selected_proposal,
                        "track_alternates": [],
                        "connection_from_previous_track": None,
                        "reason": (
                            "Use a catalog-resolved continuation while preserving "
                            "the topic-driven editorial role."
                        ),
                        "novelty_distance": selected_proposal.novelty_distance,
                        "evidence_ids": list(selected_proposal.evidence_ids),
                        "claim_support": [],
                        "narration_goal": (
                            "Connect this playable continuation to the programme "
                            "theme without unsupported song-specific claims."
                        ),
                    }
                )

            resolved_chapters.append(
                _ResolvedChapter(
                    chapter=route_chapter,
                    writer_chapter=route_chapter.model_copy(
                        update={
                            "index": len(resolved_chapters),
                            "track": selected_proposal,
                            "track_alternates": [],
                        }
                    ),
                    track=resolved,
                    music_index=None,
                )
            )
            if resolved is not None:
                added_count += 1

        trace.mark(
            "curator_continuation_ready",
            added_track_count=added_count,
            unresolved_track_count=len(continuation_unresolved),
        )
        return resolved_chapters, continuation_unresolved

    async def _extend_underfilled_locked_route_from_catalog(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        opening_track: ResolvedTrack,
        locked_successor: ResolvedTrack,
        resolved_chapters: list[_ResolvedChapter],
        used_tracks: list[ResolvedTrack],
        trace: GenerationTrace,
    ) -> list[_ResolvedChapter]:
        """Boundedly fill an undercovered live route from the real catalog.

        Preserve Curator diversity first. If that is still not enough to satisfy
        the existing duration-coverage gate, continuity wins: reuse artists from
        already-confirmed playable tracks and admit additional distinct songs
        from those exact artists. Song identity and exact-artist checks remain
        unchanged.
        """

        effective_used = list(used_tracks)
        if not any(
            _same_song_identity(locked_successor, item)
            for item in effective_used
        ):
            effective_used.append(locked_successor)
        normalized_initial = _normalize_progressive_route(
            request=request,
            resolved_chapters=resolved_chapters,
            opening_track=opening_track,
            locked_successor=locked_successor,
        )
        if not _route_underfilled(request, self.narration_ratio, normalized_initial):
            return resolved_chapters

        artist_seeds: list[TrackProposal] = []
        speculative = [
            item
            for item in resolved_chapters
            if item.chapter.track is not None and item.track is None
        ]
        playable = [
            item
            for item in resolved_chapters
            if item.chapter.track is not None and item.track is not None
        ]
        for item in [*speculative, *playable]:
            if item.chapter.track is not None:
                artist_seeds.append(item.chapter.track)
            artist_seeds.extend(item.chapter.track_alternates)

        # Emergency continuity fallback: artists whose music is already known
        # playable are safer than abandoning the entire programme when Curator
        # proposals cannot fill the requested runway.
        for track in effective_used:
            artist_seeds.append(
                TrackProposal(
                    artist=track.canonical_artist,
                    title=track.canonical_title,
                    reasons=["Confirmed playable programme artist."],
                    confidence=0.5,
                    novelty_distance=NoveltyDistance.CLOSE,
                )
            )

        unique_seeds: list[TrackProposal] = []
        seen_artists: set[str] = set()
        for seed in artist_seeds:
            artist_key = canonical_name(seed.artist)
            if not artist_key or artist_key in seen_artists:
                continue
            seen_artists.add(artist_key)
            unique_seeds.append(seed)

        def needs_more_music() -> bool:
            normalized = _normalize_progressive_route(
                request=request,
                resolved_chapters=resolved_chapters,
                opening_track=opening_track,
                locked_successor=locked_successor,
            )
            route_track_count = sum(item.track is not None for item in normalized)
            return (
                _route_underfilled(request, self.narration_ratio, normalized)
                and route_track_count < request.max_tracks
                and len(normalized) < request.max_chapters
            )

        async def append_one_from_artist(
            seed: TrackProposal,
            *,
            emergency: bool,
        ) -> bool:
            if not needs_more_music():
                return False

            artist_key = canonical_name(seed.artist)
            try:
                alternatives = await self.retrieval.search(
                    seed.artist,
                    requested_artist=seed.artist,
                    limit=10,
                )
            except ProviderError:
                return False

            for alternative in alternatives:
                if canonical_name(alternative.artist) != artist_key:
                    continue

                proposal = TrackProposal(
                    artist=alternative.artist,
                    title=alternative.title,
                    reasons=[
                        (
                            "Emergency catalog continuation for live playback."
                            if emergency
                            else "Catalog-aware continuation for an underfilled live route."
                        )
                    ],
                    similarity_dimensions=list(seed.similarity_dimensions),
                    confidence=0.5,
                    novelty_distance=(
                        seed.novelty_distance or NoveltyDistance.CLOSE
                    ),
                    evidence_ids=list(seed.evidence_ids),
                )
                candidate: ResolvedTrack | None
                if alternative.playable:
                    candidate = ResolvedTrack(
                        track_ref=alternative.track_ref,
                        canonical_artist=alternative.artist,
                        canonical_title=alternative.title,
                        duration_seconds=alternative.duration_seconds or None,
                    )
                else:
                    try:
                        candidate = await resolve_track_proposal_across_providers(
                            self.retrieval,
                            proposal,
                            limit=10,
                        )
                    except ProviderError:
                        candidate = None
                    if candidate is None:
                        continue
                if any(
                    _same_song_identity(candidate, used)
                    for used in effective_used
                ):
                    continue
                chapter = ChapterPlan(
                    index=len(resolved_chapters),
                    track=proposal,
                    narrative_role=NarrativeRole.BRIDGE,
                    reason=(
                        "Keep the live programme moving with a real playable "
                        "catalog track from an editorially relevant artist."
                    ),
                    novelty_distance=proposal.novelty_distance,
                    evidence_ids=list(proposal.evidence_ids),
                    claim_support=[],
                    narration_goal=(
                        "Connect this catalog-backed continuation to the programme "
                        "direction without unsupported song-specific claims."
                    ),
                )
                resolved_chapters.append(
                    _ResolvedChapter(
                        chapter=chapter,
                        writer_chapter=chapter,
                        track=candidate,
                        music_index=None,
                    )
                )
                effective_used.append(candidate)
                trace.mark(
                    (
                        "track_catalog_emergency_continuation_resolved"
                        if emergency
                        else "track_catalog_continuation_resolved"
                    ),
                    resolved_track_count=len(effective_used),
                )
                return True
            return False

        # Pass 1: preserve route diversity by taking at most one continuation
        # from each Curator/confirmed artist.
        for seed in unique_seeds:
            if not needs_more_music():
                break
            await append_one_from_artist(seed, emergency=False)

        # Pass 2: continuity is the hard requirement. Round-robin through the
        # same exact artists and take additional distinct songs until the
        # existing coverage gate or configured programme bounds are satisfied.
        while needs_more_music():
            progress = False
            for seed in unique_seeds:
                if not needs_more_music():
                    break
                if await append_one_from_artist(seed, emergency=True):
                    progress = True
            if not progress:
                break

        return resolved_chapters

    async def _prepare_intelligence(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        request_id: str | None = None,
        locked_successor: ResolvedTrack | None = None,
        reserved_tracks: Sequence[ResolvedTrack] = (),
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

        if locked_successor is not None:
            fast_result = _locked_successor_fast_result(
                intelligence_input,
                locked_successor,
                request_id=request_id,
            )
            fast_path_ms = 0
        else:
            fast_started = perf_counter()
            try:
                fast_result = await self.fast_path.run(
                    intelligence_input,
                    request_id=request_id,
                )
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

        catalog_pool = await self._build_catalog_pool(
            request,
            fast_plan=fast_result.plan,
            bundle=bundle,
            reserved_tracks=(
                (*reserved_tracks, locked_successor)
                if locked_successor is not None
                else reserved_tracks
            ),
            trace=trace,
        )
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
                catalog_pool=catalog_pool,
                required_artists=request.required_artists,
                variety_seed=request.variety_seed,
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
        if request.required_artists:
            chapters = await self._cover_required_artists(
                request,
                chapters,
                bundle=bundle,
                catalog_pool=catalog_pool,
                reserved_tracks=reserved_tracks,
                locked_successor=locked_successor,
                trace=trace,
            )
        skeleton = skeleton.model_copy(update={"chapters": chapters})
        trace.mark("program_skeleton_ready", chapter_count=len(chapters))

        resolution_started = perf_counter()
        resolved_chapters: list[_ResolvedChapter] = []
        unresolved: list[UnresolvedAssemblyProposal] = []
        used_tracks = list(reserved_tracks)
        for chapter in chapters:
            resolved: ResolvedTrack | None = None
            selected_proposal: TrackProposal | None = None
            replacement_kind: str | None = None
            if chapter.track is not None:
                candidates = [chapter.track, *chapter.track_alternates]
                attempted = {_proposal_identity_key(item) for item in candidates}
                last_resolution_reason = "no exact playable catalog match"
                for candidate_rank, proposal in enumerate(candidates):
                    try:
                        candidate = await self._resolve_proposal_track(proposal, catalog_pool)
                    except ProviderError as error:
                        candidate = None
                        last_resolution_reason = (
                            f"resolution provider failed: {type(error).__name__}"
                        )
                    if candidate is None:
                        continue
                    if any(
                        _same_song_identity(candidate, used)
                        for used in used_tracks
                    ):
                        last_resolution_reason = "duplicate episode song identity"
                        trace.mark(
                            "duplicate_resolved_track_skipped",
                            chapter_index=chapter.index,
                            candidate_rank=candidate_rank + 1,
                        )
                        continue
                    resolved = candidate
                    selected_proposal = proposal
                    used_tracks.append(candidate)
                    if candidate_rank > 0:
                        trace.mark(
                            "track_alternate_resolved",
                            chapter_index=chapter.index,
                            candidate_rank=candidate_rank + 1,
                            candidate_count=len(candidates),
                        )
                    break
                if resolved is None:
                    replacement = await self._resolve_catalog_replacement(
                        chapter,
                        bundle,
                        fast_result.plan,
                        attempted=attempted,
                        used_tracks=used_tracks,
                    )
                    if replacement is not None:
                        resolved, selected_proposal, replacement_kind = replacement
                        used_tracks.append(resolved)
                        trace.mark(
                            "track_catalog_replacement_resolved",
                            chapter_index=chapter.index,
                            replacement_kind=replacement_kind,
                        )
                    else:
                        unresolved.append(
                            UnresolvedAssemblyProposal(
                                chapter_index=chapter.index,
                                proposal=chapter.track,
                                reason=last_resolution_reason,
                            )
                        )
                        trace.mark(
                            "track_slot_unresolved",
                            chapter_index=chapter.index,
                            candidate_count=len(candidates),
                        )
            route_chapter = chapter
            if replacement_kind is not None and selected_proposal is not None:
                route_chapter = track_true_chapter(chapter, selected_proposal)
            resolved_chapters.append(
                _ResolvedChapter(
                    chapter=route_chapter,
                    writer_chapter=route_chapter.model_copy(
                        update={
                            "index": len(resolved_chapters),
                            "track": selected_proposal,
                            "track_alternates": [],
                        }
                    ),
                    track=resolved,
                    music_index=None,
                )
            )
        if locked_successor is not None and reserved_tracks:
            opening_track = reserved_tracks[0]
            continuation_started = perf_counter()
            resolved_chapters, continuation_unresolved = (
                await self._extend_underfilled_route_with_curator(
                    request,
                    bundle=bundle,
                    fast_plan=fast_result.plan,
                    opening_track=opening_track,
                    locked_successor=locked_successor,
                    resolved_chapters=resolved_chapters,
                    used_tracks=used_tracks,
                    trace=trace,
                    catalog_pool=catalog_pool,
                )
            )
            curator_ms += _elapsed_ms(continuation_started)
            unresolved.extend(continuation_unresolved)

            resolved_chapters = await self._extend_underfilled_locked_route_from_catalog(
                request,
                opening_track=opening_track,
                locked_successor=locked_successor,
                resolved_chapters=resolved_chapters,
                used_tracks=used_tracks,
                trace=trace,
            )
        resolved_chapters = _reindex_resolved_chapters(resolved_chapters)
        resolved_chapters = _reconcile_route_text(
            resolved_chapters,
            known_artists=known_artist_names(
                [
                    *(
                        proposal
                        for chapter in chapters
                        for proposal in (chapter.track, *chapter.track_alternates)
                        if proposal is not None
                    ),
                    *_pool_proposals(fast_result.plan, bundle),
                ],
                request.required_artists,
                request.topic,
            ),
            earlier_tracks=(
                (*reserved_tracks, locked_successor)
                if locked_successor is not None
                else reserved_tracks
            ),
            trace=trace,
        )
        resolution_ms = _elapsed_ms(resolution_started)
        trace.mark(
            "tracks_resolved",
            resolved_count=sum(item.track is not None for item in resolved_chapters),
            unresolved_count=len(unresolved),
        )
        try:
            slot_contexts = _apply_host_mode_to_slot_contexts(
                _build_narration_slot_contexts(resolved_chapters),
                request.presentation_intent.host_mode,
            )
        except NarrationPlacementError as error:
            raise EpisodeAssemblyError(
                str(error),
                stage="writer_normalization",
                reason_code="narration_slot_derivation_failed",
                diagnostics={"narration_failure_boundary": "slot_derivation"},
            ) from error

        route_tracks = [
            *reserved_tracks,
            *([locked_successor] if locked_successor is not None else []),
            *(item.track for item in resolved_chapters if item.track is not None),
        ]
        unmet = unfulfilled_artists(request.required_artists, route_tracks)
        if unmet:
            trace.mark("required_artists_unfulfilled", count=len(unmet))

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
            catalog_pool=catalog_pool,
            unfulfilled_artists=tuple(unmet),
        )

    async def _cover_required_artists(
        self,
        request: LiveEpisodeAssemblyRequest,
        chapters: list[ChapterPlan],
        *,
        bundle: ResearchBundle,
        catalog_pool: CatalogPool | None,
        reserved_tracks: Sequence[ResolvedTrack],
        locked_successor: ResolvedTrack | None,
        trace: GenerationTrace,
    ) -> list[ChapterPlan]:
        """Put every artist the request names into the plan, from verified-playable tracks.

        The Curator is told to cover them, but it plans from a candidate list and memory and
        can leave one out.  A missing artist is searched in the catalog (the pool already did
        when enabled) and given the chapter of an artist the request did not name.
        """

        credited = [
            *(track.canonical_artist for track in reserved_tracks),
            *([locked_successor.canonical_artist] if locked_successor is not None else []),
            *(chapter.track.artist for chapter in chapters if chapter.track is not None),
        ]
        absent = [
            name
            for name in request.required_artists
            if not covered_artists([name], credited)
        ]
        if not absent:
            return chapters
        pool = catalog_pool
        if pool is None:
            pool = await self._build_coverage_pool(absent, reserved_tracks, trace)
        # Without a reserved opening, the first chapter is the track the listener starts with.
        protected = set() if reserved_tracks else {0}
        if locked_successor is not None:
            protected.update(
                index
                for index, chapter in enumerate(chapters)
                if chapter.track is not None
                and canonical_name(chapter.track.title)
                == canonical_name(locked_successor.canonical_title)
            )
        patched, missing = ensure_required_coverage(
            chapters,
            pool,
            request.required_artists,
            bundle.evidence,
            reserved=(
                (*reserved_tracks, locked_successor)
                if locked_successor is not None
                else reserved_tracks
            ),
            protected_indices=sorted(protected),
        )
        trace.mark(
            "required_artists_checked",
            required_count=len(request.required_artists),
            absent_count=len(absent),
            patched_count=len(absent) - len(missing),
        )
        logger.info(
            "required_artists_checked required=%d absent=%d patched=%d unpatched=%d",
            len(request.required_artists),
            len(absent),
            len(absent) - len(missing),
            len(missing),
        )
        return patched

    async def _build_coverage_pool(
        self,
        artists: Sequence[str],
        reserved_tracks: Sequence[ResolvedTrack],
        trace: GenerationTrace,
    ) -> CatalogPool | None:
        """A small pool of the named artists' playable tracks, when the full pool is off."""

        try:
            pool = await CatalogPoolBuilder(self.retrieval, _COVERAGE_POOL_CONFIG).build(
                artist_queries=list(artists)
            )
        except Exception as error:  # noqa: BLE001 - optional optimisation, degrade quietly
            logger.warning("coverage_pool_failed error_type=%s", type(error).__name__)
            trace.mark("coverage_pool_failed", error_type=type(error).__name__)
            return None
        return pool.model_copy(
            update={
                "entries": [
                    entry
                    for entry in pool.entries
                    if not any(
                        _same_song_identity(reserved, entry.resolved_track())
                        for reserved in reserved_tracks
                    )
                ]
            }
        )

    async def _build_catalog_pool(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        fast_plan: FastStartPlan,
        bundle: ResearchBundle,
        reserved_tracks: Sequence[ResolvedTrack],
        trace: GenerationTrace,
    ) -> CatalogPool | None:
        """Build the verified-playable pool, or None when disabled or unavailable.

        The pool only improves selection; any failure here must never stop generation.
        """

        builder = self.catalog_pool_builder
        if builder is None and request.required_artists:
            # A request that names artists is where an exact-title miss costs most: the
            # Curator names a plausible album as a song, the catalog has no such track, and
            # the route comes up short.  Live, 2 of 9 such programmes failed without the pool
            # and 4 of 4 succeeded with it, so these requests use it even when the flag is off.
            builder = CatalogPoolBuilder(self.retrieval, _NAMED_ARTIST_POOL_CONFIG)
        if builder is None:
            return None
        try:
            proposals = _pool_proposals(fast_plan, bundle)
            pool = await builder.build(
                proposals=proposals,
                artist_queries=_pool_artist_queries(
                    proposals, request.required_artists, request.topic
                ),
                keyword_queries=[request.topic],
            )
        except Exception as error:  # noqa: BLE001 - optional optimisation, degrade quietly
            logger.warning("catalog_pool_failed error_type=%s", type(error).__name__)
            trace.mark("catalog_pool_failed", error_type=type(error).__name__)
            return None
        # Never offer a song the programme has already reserved (e.g. the opening track).
        pool = pool.model_copy(
            update={
                "entries": [
                    entry
                    for entry in pool.entries
                    if not any(
                        _same_song_identity(reserved, entry.resolved_track())
                        for reserved in reserved_tracks
                    )
                ]
            }
        )
        logger.info(
            "catalog_pool_ready entries=%d playable=%d unplayable=%d not_found=%d "
            "provider_error=%d verifications=%d search_failures=%d failure_kinds=%s elapsed_ms=%d "
            "truncated=%s",
            len(pool.entries),
            pool.count(AvailabilityStatus.PLAYABLE),
            pool.count(AvailabilityStatus.UNPLAYABLE),
            pool.count(AvailabilityStatus.NOT_FOUND),
            pool.count(AvailabilityStatus.PROVIDER_ERROR),
            pool.verification_count,
            pool.search_failure_count,
            dict(sorted(pool.failure_kinds.items())),
            pool.elapsed_ms,
            pool.truncated,
        )
        trace.mark(
            "catalog_pool_ready",
            entry_count=len(pool.entries),
            playable_count=pool.count(AvailabilityStatus.PLAYABLE),
            unplayable_count=pool.count(AvailabilityStatus.UNPLAYABLE),
            not_found_count=pool.count(AvailabilityStatus.NOT_FOUND),
            verification_count=pool.verification_count,
            elapsed_ms=pool.elapsed_ms,
            truncated=pool.truncated,
        )
        return pool

    async def _resolve_proposal_track(
        self, proposal: TrackProposal, catalog_pool: CatalogPool | None
    ) -> ResolvedTrack | None:
        """Resolve a Curator proposal, trusting only entries already verified playable."""

        if catalog_pool is not None:
            entry = catalog_pool.find(proposal.artist, proposal.title)
            if entry is not None:
                return entry.resolved_track()
        return await resolve_track_proposal_across_providers(self.retrieval, proposal)

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
            target_narration_ratio=narration_ratio_for_host_mode(
                request.presentation_intent.host_mode,
                full_ratio=self.narration_ratio,
            ),
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
                    host_mode=request.presentation_intent.host_mode,
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
                require_final_slot=(
                    request.presentation_intent.host_mode is not HostMode.NONE
                ),
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




def _locked_successor_fast_result(
    request: FastResearchInput,
    locked_successor: ResolvedTrack,
    *,
    request_id: str,
) -> FastPathResult:
    """Reconstruct deterministic FastStart context from durable successor identity.

    The actual FastStart provider already chose and resolved this track before it
    entered the Episode. Re-running that paid/model stage would add latency and
    could disagree with the promise already made to playback.
    """

    proposal = TrackProposal(
        artist=locked_successor.canonical_artist,
        title=locked_successor.canonical_title,
        reasons=["FastStart successor already persisted by the runtime."],
        confidence=1.0,
    )
    language = resolve_output_language(request.output_language, request.topic)
    if language is OutputLanguage.ZH_CN:
        narration_text = "下一首已经准备好，我们会在播放过程中继续完善后面的节目路线。"
    elif language is OutputLanguage.JA_JP:
        narration_text = "次の曲は準備できています。再生中に、この先の番組構成を整えていきます。"
    else:
        narration_text = (
            "The next track is already prepared while the rest of the route is refined."
        )
    research_plan = generic_research_plan(request)
    plan = FastStartPlan(
        anchor_understanding=[
            (
                "Continue from the opening through the already prepared successor: "
                f"{locked_successor.canonical_artist} - "
                f"{locked_successor.canonical_title}"
            )
        ],
        immediate_taste_hypotheses=[],
        next_candidates=[proposal],
        selected_next_track=proposal,
        first_narration=NarrationScript(
            text=narration_text,
            intended_duration_seconds=8,
        ),
        research_plan=research_plan,
    )
    bundle = ResearchBundle(
        anchors=[
            *request.anchor_tracks,
            f"{locked_successor.canonical_artist} - {locked_successor.canonical_title}",
        ],
        taste_hypotheses=[],
        evidence=[],
        candidates=[proposal],
        research_plan=research_plan,
        uncertainties=[],
    )
    trace = GenerationTrace(request_id=request_id)
    trace.mark(
        "fast_successor_reused",
        track_artist=locked_successor.canonical_artist,
        track_title=locked_successor.canonical_title,
    )
    return FastPathResult(
        research=FastResearchResult(
            bundle=bundle,
            elapsed_ms=0,
            queries=[],
        ),
        plan=plan,
        trace=trace,
        elapsed_ms=0,
    )


_GENERIC_ARTIST_WORDS = {
    "the",
    "trio",
    "quartet",
    "quintet",
    "sextet",
    "band",
    "ensemble",
    "orchestra",
    "group",
}


def _identity_words(value: str) -> tuple[str, ...]:
    return tuple(
        re.findall(r"[\w]+", strip_latin_accents(canonical_name(value)), flags=re.UNICODE)
    )


def _artist_identity_words(value: str) -> frozenset[str]:
    return frozenset(
        word
        for word in _identity_words(value)
        if word not in _GENERIC_ARTIST_WORDS
    )


def _route_summary(
    session: ProgressiveAssemblySession, episode: LiveEpisode
) -> tuple[list[str], list[str]]:
    """The tracks this programme really plays, and artists the plan named but will not play.

    Narration is written from the plan's evidence; when a planned track could not be played the
    Writer must not talk about it as if the listener heard it.
    """

    played: list[str] = []
    played_artists: set[str] = set()

    def add(artist: str, title: str) -> None:
        label = f"{artist} - {title}"
        if label not in played:
            played.append(label)
        played_artists.add(canonical_name(artist))

    for segment in episode.ordered_segments:
        if isinstance(segment, MusicSegment) and segment.artist and segment.title:
            add(segment.artist, segment.title)
    for item in session.chapters:
        if item.resolved_track is not None:
            add(item.resolved_track.canonical_artist, item.resolved_track.canonical_title)

    # An artist the listener asked for but the route could not play is never to be talked
    # about as if it were part of the programme.
    unplayed: list[str] = [
        name for name in session.unfulfilled_artists if canonical_name(name) not in played_artists
    ]
    for chapter in session.skeleton.chapters:
        for proposal in (chapter.track, *chapter.track_alternates):
            if proposal is None:
                continue
            folded = canonical_name(proposal.artist)
            if any(folded in artist or artist in folded for artist in played_artists):
                continue
            if proposal.artist not in unplayed:
                unplayed.append(proposal.artist)
    return played, unplayed


def _used_openers(episode: LiveEpisode) -> list[str]:
    """How the narration already authored for this programme begins, in order."""

    openers: list[str] = []
    for segment in episode.ordered_segments:
        if (
            isinstance(segment, NarrationSegment)
            and segment.narration_text
            and segment.state is not SegmentState.SKIPPED
        ):
            opener = opener_of(segment.narration_text)
            if opener and opener not in openers:
                openers.append(opener)
    return openers


_TRANSLATED_TITLE_SECONDS = 3


def _is_cjk_only(title: str) -> bool:
    letters = [char for char in title if char.isalpha()]
    return bool(letters) and all("\u3040" <= char <= "\u9fff" for char in letters)


def _is_latin_only(title: str) -> bool:
    letters = [char for char in title if char.isalpha()]
    return bool(letters) and all(char.isascii() for char in letters)


def _translated_title_of_same_length(left: ResolvedTrack, right: ResolvedTrack) -> bool:
    """One recording listed under its original title and a Chinese rendering of it.

    The catalog lists "What A Wonderful World" and "多美妙的世界" as separate tracks of the
    same artist.  Without a shared word the titles cannot be compared, so this accepts the
    pair only when one title is entirely Chinese/Japanese, the other entirely Latin, and the
    recordings' lengths agree to within a few seconds (both lengths must be known).
    """

    if left.duration_seconds is None or right.duration_seconds is None:
        return False
    if abs(left.duration_seconds - right.duration_seconds) > _TRANSLATED_TITLE_SECONDS:
        return False
    return (_is_cjk_only(left.canonical_title) and _is_latin_only(right.canonical_title)) or (
        _is_latin_only(left.canonical_title) and _is_cjk_only(right.canonical_title)
    )


def _same_song_identity(left: ResolvedTrack | None, right: ResolvedTrack) -> bool:
    """Conservatively collapse catalog/version aliases of the same episode song.

    Exact catalog identity remains authoritative for playback. This helper is
    only an episode-level repetition guard: titles must normalize identically,
    and the artist identity must be the same or one must be a strict extension
    such as "Bill Evans" vs "Bill Evans Trio".
    """

    if left is None:
        return False
    if left.track_ref == right.track_ref:
        return True
    if song_title_key(left.canonical_title) != song_title_key(right.canonical_title) and not (
        _translated_title_of_same_length(left, right)
    ):
        return False
    left_artist = _artist_identity_words(left.canonical_artist)
    right_artist = _artist_identity_words(right.canonical_artist)
    if not left_artist or not right_artist:
        return (
            canonical_name(left.canonical_artist)
            == canonical_name(right.canonical_artist)
        )
    return left_artist <= right_artist or right_artist <= left_artist


def _same_resolved_track(left: ResolvedTrack | None, right: ResolvedTrack) -> bool:
    """Compare durable catalog identity exactly."""

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


def _lock_successor_after_opening(
    chapters: list[_ResolvedChapter],
    locked_successor: ResolvedTrack | None,
) -> list[_ResolvedChapter]:
    """Keep a persisted FastStart successor as the Episode's second music identity."""

    if locked_successor is None or not chapters:
        return chapters
    if _same_resolved_track(chapters[0].track, locked_successor):
        return chapters

    successor_index = next(
        (
            index
            for index, item in enumerate(chapters[1:], start=1)
            if _same_resolved_track(item.track, locked_successor)
        ),
        None,
    )
    if successor_index is None:
        proposal = TrackProposal(
            artist=locked_successor.canonical_artist,
            title=locked_successor.canonical_title,
            reasons=["FastStart successor already persisted by the runtime."],
            confidence=1.0,
        )
        plan = ChapterPlan(
            index=1,
            track=proposal,
            narrative_role=NarrativeRole.BRIDGE,
            reason="Preserve the already prepared FastStart successor.",
            narration_goal=(
                "Connect the opening to the already prepared next track without "
                "inventing unsupported facts."
            ),
        )
        successor = _ResolvedChapter(
            chapter=plan,
            writer_chapter=plan,
            track=locked_successor,
            music_index=None,
        )
    else:
        successor = chapters[successor_index]

    remainder = [
        item
        for index, item in enumerate(chapters[1:], start=1)
        if index != successor_index
        and not _same_resolved_track(item.track, locked_successor)
    ]
    locked_route = [chapters[0], successor, *remainder]
    if successor_index == 1:
        return locked_route

    # Inserting or moving the persisted successor changes route adjacency.
    # Curator connection metadata described the old neighbors, so retaining it
    # would invite Writer to explain a relation that no longer exists.
    cleared: list[_ResolvedChapter] = [locked_route[0]]
    for item in locked_route[1:]:
        chapter = item.chapter.model_copy(
            update={"connection_from_previous_track": None}
        )
        writer_chapter = item.writer_chapter.model_copy(
            update={"connection_from_previous_track": None}
        )
        cleared.append(
            _ResolvedChapter(
                chapter=chapter,
                writer_chapter=writer_chapter,
                track=item.track,
                music_index=item.music_index,
            )
        )
    return cleared


def _dedupe_progressive_song_route(
    chapters: list[_ResolvedChapter],
    *,
    protected_prefix: int,
) -> list[_ResolvedChapter]:
    """Drop later semantic song repeats while preserving immutable route prefix."""

    kept: list[_ResolvedChapter] = []
    seen: list[ResolvedTrack] = []
    for index, item in enumerate(chapters):
        if item.track is None:
            kept.append(item)
            continue
        if index >= protected_prefix and any(
            _same_song_identity(item.track, prior) for prior in seen
        ):
            continue
        kept.append(item)
        seen.append(item.track)
    return kept


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


def _reconcile_route_text(
    items: list[_ResolvedChapter],
    *,
    known_artists: Sequence[str],
    earlier_tracks: Sequence[ResolvedTrack],
    trace: GenerationTrace,
) -> list[_ResolvedChapter]:
    """Make every chapter's text describe the track that actually plays.

    The Writer trusts a chapter's reason, goal, claims and evidence.  When resolution played
    an alternate instead of the planned track, or the text is about an artist the listener is
    not hearing, the chapter falls back to generic text for the played track.
    """

    heard = [track.canonical_artist for track in earlier_tracks]
    result: list[_ResolvedChapter] = []
    for item in items:
        track = item.track
        if track is None:
            result.append(item)
            continue
        selected = item.writer_chapter.track
        cause: str | None = None
        foreign: list[str] = []
        if used_an_alternate(item.chapter, selected):
            cause = "alternate_track"
        else:
            foreign = foreign_artists(
                item.writer_chapter, track.canonical_artist, known_artists, heard
            )
            if foreign:
                cause = "text_names_other_artist"
        if cause is not None:
            trace.mark(
                "chapter_text_neutralised",
                chapter_index=item.writer_chapter.index,
                cause=cause,
                foreign_artist_count=len(foreign),
            )
            logger.info(
                "chapter_text_neutralised chapter=%d cause=%s foreign_artists=%d",
                item.writer_chapter.index,
                cause,
                len(foreign),
            )
            item = replace(
                item,
                chapter=track_true_chapter(item.chapter, selected),
                writer_chapter=track_true_chapter(item.writer_chapter, selected),
            )
        heard.append(track.canonical_artist)
        result.append(item)
    return result


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


def _normalize_progressive_route(
    *,
    request: LiveEpisodeAssemblyRequest,
    resolved_chapters: list[_ResolvedChapter],
    opening_track: ResolvedTrack,
    locked_successor: ResolvedTrack | None,
) -> list[_ResolvedChapter]:
    """Apply the exact route-shaping rules used by the live session builder."""

    locked_route = _lock_successor_after_opening(
        _normalize_opening_resolved_route(
            resolved_chapters,
            opening_track,
        ),
        locked_successor,
    )
    viable_route = [
        item
        for item in locked_route
        if item.chapter.track is None or item.track is not None
    ]
    deduped_route = _dedupe_progressive_song_route(
        viable_route,
        protected_prefix=2 if locked_successor is not None else 1,
    )
    return _reindex_resolved_chapters(
        _bound_progressive_resolved_route(
            deduped_route,
            max_tracks=request.max_tracks,
            max_chapters=request.max_chapters,
        )
    )


def _build_progressive_session(
    *,
    request: LiveEpisodeAssemblyRequest,
    prepared: _PreparedIntelligence,
    opening_track: ResolvedTrack,
    locked_successor: ResolvedTrack | None = None,
    narration_ratio: float,
) -> ProgressiveAssemblySession:
    """Build the pre-Writer session from route identities and slot contexts."""

    normalized = _fit_route_to_time_budget(
        _normalize_progressive_route(
            request=request,
            resolved_chapters=prepared.resolved_chapters,
            opening_track=opening_track,
            locked_successor=locked_successor,
        ),
        request=request,
        narration_ratio=narration_ratio,
        # The opening and at least one more track: a programme is never cut to its opening.
        keep_at_least=2,
    )
    try:
        all_slot_contexts = _apply_host_mode_to_slot_contexts(
            _build_narration_slot_contexts(normalized),
            request.presentation_intent.host_mode,
        )
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
        if (
            # A selected music slot that failed catalog resolution is speculative
            # and should disappear from the live route rather than survive as a
            # narration-only chapter about music that will never play. Genuine
            # narrative-only Curator chapters remain valid.
            (item.chapter.track is None or item.track is not None)
            and (item.track is not None or contexts)
        )
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
    if future_music_count < 1:
        raise EpisodeAssemblyError(
            "progressive route has no resolved future music after the opening",
            stage="resolution",
            reason_code="no_progressive_future_music",
            diagnostics={
                "resolved_future_track_count": future_music_count,
                "unresolved_track_count": len(prepared.unresolved),
                "required_future_track_count": 1,
            },
        )

    target_narration_ratio = narration_ratio_for_host_mode(
        request.presentation_intent.host_mode,
        full_ratio=narration_ratio,
    )
    required_resolved_music_seconds = _required_progressive_music_seconds(
        request,
        narration_ratio,
    )
    # Real lengths where the catalog reported them: a route of a few long songs is as full as
    # one of many short ones (the route was fitted to its time budget above).  A catalog of
    # very short clips (previews, the mock provider) is still judged by track count, as it was
    # before lengths were known, so the real-length view can only accept more routes.
    resolved_lengths = [opening_track.duration_seconds] + [
        item.track.duration_seconds for item in future if item.track is not None
    ]
    estimated_resolved_music_seconds = max(
        sum(track_seconds(length) for length in resolved_lengths),
        len(resolved_lengths) * _ESTIMATED_TRACK_DURATION_SECONDS,
    )
    if estimated_resolved_music_seconds < required_resolved_music_seconds:
        raise EpisodeAssemblyError(
            "progressive route duration coverage is too short to be finalized",
            stage="resolution",
            reason_code="insufficient_progressive_duration_coverage",
            diagnostics={
                "estimated_resolved_music_seconds": estimated_resolved_music_seconds,
                "required_resolved_music_seconds": required_resolved_music_seconds,
                "desired_duration_seconds": request.desired_duration_seconds,
                "unresolved_track_count": len(prepared.unresolved),
            },
        )

    timing_plan = build_program_timing_plan(
        desired_total_seconds=request.desired_duration_seconds,
        target_narration_ratio=target_narration_ratio,
        resolved_music_seconds=sum(
            track_seconds(item.track.duration_seconds) for item in future if item.track is not None
        ),
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
        station=request.station,
        required_artists=list(request.required_artists),
        unfulfilled_artists=list(prepared.unfulfilled_artists),
        presentation_intent=request.presentation_intent,
        opening_track_ref=opening_track.track_ref,
        fast_plan=prepared.fast_result.plan,
        research=prepared.bundle,
        skeleton=prepared.skeleton.model_copy(
            update={
                "chapters": [
                    normalized[0].writer_chapter,
                    *[item.writer_chapter for item in future],
                ]
            }
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

    def gap_is_owned(
        kind: str,
        left_music_index: int | None,
        right_music_index: int | None,
    ) -> bool:
        return (kind, left_music_index, right_music_index) in owned_gap_keys

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
            gap_kind = "final" if is_final_chapter else "inter-track"
            gap_right = None if is_final_chapter else upcoming_music_index
            if gap_is_owned(gap_kind, previous_music_index, gap_right):
                # Curator may emit several narrative-only beats for the same
                # physical music gap. Keep the earliest owner rather than
                # failing the whole Episode or inventing an extra playback gap.
                contexts.append(chapter_slots)
                continue
            claim_gap(
                gap_kind,
                previous_music_index,
                gap_right,
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
            if gap_is_owned("opening", None, upcoming_music_index):
                # Multiple leading narrative beats still map to one physical
                # opening gap after the immediate first track. The earliest
                # beat owns it; later duplicates do not block music planning.
                contexts.append(chapter_slots)
                continue
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

def _apply_host_mode_to_slot_contexts(
    contexts: list[list[NarrationSlotContext]],
    mode: HostMode,
) -> list[list[NarrationSlotContext]]:
    """Apply deterministic host density after truthful gap ownership is known.

    FULL keeps every owned gap. LIGHT keeps the first direct music bridge and
    then every other direct bridge, while preserving curated narrative beats
    and the final outro. NONE owns no narration slots.
    """

    if mode is HostMode.FULL:
        return [list(items) for items in contexts]
    if mode is HostMode.NONE:
        return [[] for _ in contexts]

    direct_gap_index = 0
    filtered: list[list[NarrationSlotContext]] = []
    for chapter_contexts in contexts:
        kept: list[NarrationSlotContext] = []
        for context in chapter_contexts:
            if context.is_final:
                kept.append(context)
                continue
            if (
                context.placement is NarrationSlotPlacement.BEFORE_TRACK
                and context.chapter_track is not None
            ):
                if direct_gap_index % 2 == 0:
                    kept.append(context)
                direct_gap_index += 1
                continue
            # Narrative-only / opening beats were explicitly created by the
            # editorial route and remain valuable even in LIGHT mode.
            kept.append(context)
        filtered.append(kept)
    return filtered


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
    """Publish continuity-critical music before optional narration authoring."""

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

    @scoped_to_episode
    async def generate_next(self, episode: LiveEpisode) -> GeneratedChapter | None:
        """Prepare the next route step without waiting for Writer or TTS."""
        chapter = self.session.next_chapter(episode)
        if chapter is None:
            return None

        # Narrative-only / unresolved speculative beats must never hold the
        # continuity queue in front of a later playable track. Persist a skipped
        # marker so durable route reconstruction can advance past the beat.
        if chapter.resolved_track is None:
            return GeneratedChapter(
                chapter_id=chapter.chapter_id,
                segments=[
                    NarrationSegment(
                        id=f"{chapter.chapter_id}:narration:0",
                        chapter_id=chapter.chapter_id,
                        order=(episode.ordered_segments[-1].order + 1),
                        state=SegmentState.SKIPPED,
                        planned_duration_seconds=max(1, chapter.target_narration_seconds),
                        title="Optional narration skipped",
                    )
                ],
            )

        try:
            prepared_tracks = await self.composer.prepare_tracks([chapter.resolved_track])
            playable = self.composer.compose_prepared(
                prepared_tracks,
                RadioScript(blocks=[], intended_duration_seconds=1),
            )
        except ProviderError as error:
            raise EpisodeAssemblyError(str(error), stage="progressive_chunk") from error
        except (UnresolvedTrackError, ValueError) as error:
            raise EpisodeAssemblyError(str(error), stage="progressive_chunk") from error

        music = [
            segment
            for segment in playable.segments
            if isinstance(segment, MusicSegment)
        ]
        if len(music) != 1 or not music[0].is_audio_ready:
            raise EpisodeAssemblyError(
                "progressive chapter did not produce exactly one ready music source",
                stage="progressive_chunk",
                reason_code="missing_playable_music",
            )
        segments: list[MusicSegment | NarrationSegment] = []
        if (
            self.session.presentation_intent.host_mode is not HostMode.NONE
            and chapter.slot_contexts
        ):
            segments.append(
                _pending_narration_placeholder(
                    chapter.chapter_id,
                    planned_duration_seconds=max(1, chapter.target_narration_seconds),
                )
            )
        segments.extend(music)
        return _generated_runtime_chapter(
            chapter.chapter_id,
            segments,
            base_order=episode.ordered_segments[-1].order + 1,
        )

    async def author_narration(
        self,
        episode: LiveEpisode,
        chapter_id: str,
    ) -> GeneratedChapter | None:
        """Author SCRIPT_READY narration for one still-speculative route chapter."""
        chapter = next(
            (item for item in self.session.chapters if item.chapter_id == chapter_id),
            None,
        )
        if (
            chapter is None
            or not chapter.slot_contexts
            or (
                chapter.resolved_track is None
                and chapter.chapter.track is not None
            )
        ):
            return None

        chapter_segments = [
            segment
            for segment in episode.ordered_segments
            if segment.chapter_id == chapter_id
        ]
        if not chapter_segments:
            return None
        chapter_start_order = min(segment.order for segment in chapter_segments)

        existing_music = [
            segment
            for segment in chapter_segments
            if isinstance(segment, MusicSegment)
        ]
        prepared_tracks: list[PreparedMusicAsset] = []
        chapter_music_index: int | None = None
        if chapter.resolved_track is not None:
            if len(existing_music) != 1:
                return None
            music = existing_music[0]
            if (
                music.track_ref != chapter.resolved_track.track_ref
                or music.artist != chapter.resolved_track.canonical_artist
                or music.title != chapter.resolved_track.canonical_title
                or not music.audio_source_url
            ):
                raise EpisodeAssemblyError(
                    "persisted music identity does not match narration route",
                    stage="writer_normalization",
                    reason_code="narration_music_identity_mismatch",
                )
            prepared_tracks = [
                PreparedMusicAsset(
                    track=chapter.resolved_track,
                    asset=AudioAsset(
                        asset_id=music.asset_ref or f"persisted:{music.track_ref}",
                        asset_type=AudioAssetType.MUSIC,
                        provider="persisted",
                        playback_url=music.audio_source_url,
                        duration=music.duration_seconds,
                    ),
                )
            ]
            chapter_music_index = 0
        elif existing_music:
            raise EpisodeAssemblyError(
                "trackless narration chapter unexpectedly contains music",
                stage="writer_normalization",
                reason_code="narration_trackless_music_mismatch",
            )

        # Everything already authored for this programme, not only what has been played:
        # narration is written ahead of playback, so "committed" would let facts repeat.
        previous_context = " ".join(
            segment.narration_text
            for segment in episode.ordered_segments
            if (
                isinstance(segment, NarrationSegment)
                and segment.state is not SegmentState.SKIPPED
                and segment.narration_text
            )
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
        route_tracks, unplayed_artists = _route_summary(self.session, episode)
        has_previous_music = any(
            isinstance(segment, MusicSegment) and segment.order < chapter_start_order
            for segment in episode.ordered_segments
        )

        try:
            script = await self.writer.write(
                chapter.chapter,
                self.session.research.evidence,
                previous_committed_context=previous_context,
                next_track_metadata=next_track_metadata,
                host_mode=self.session.presentation_intent.host_mode,
                target_duration_seconds=chapter.target_narration_seconds,
                output_language=self.session.output_language,
                station=self.session.station,
                voice_seed=episode.seed_id,
                used_openers=_used_openers(episode),
                route_tracks=route_tracks,
                unplayed_artists=unplayed_artists,
                unfulfilled_artists=self.session.unfulfilled_artists,
                topic=self.session.topic,
                slot_contexts=chapter.slot_contexts,
            )
            radio_script, _ = _assemble_writer_scripts(
                [script],
                len(prepared_tracks),
                chapter_music_indices=[chapter_music_index],
                slot_contexts=[chapter.slot_contexts],
                chapter_connections=[chapter.chapter.connection_from_previous_track],
                previous_music_indices=[0 if has_previous_music else None],
                require_final_slot=(
                    bool(self.session.chapters)
                    and chapter.chapter_id == self.session.chapters[-1].chapter_id
                ),
            )
            playable = self.composer.compose_prepared(prepared_tracks, radio_script)
            _assert_narration_blocks_materialized(radio_script, playable)
        except (
            ProviderError,
            NarrationPlacementError,
            EpisodeAssemblyError,
            ValueError,
        ) as error:
            # Writer is the quality layer, not the existence guarantee. P0
            # deliberately prefers a clean music-only gap over canned catalog
            # copy when Writer cannot produce a trustworthy bridge.
            logger.warning(
                "narration_authoring_failed chapter_id=%s error_type=%s host_mode=%s",
                chapter.chapter_id,
                type(error).__name__,
                self.session.presentation_intent.host_mode.value,
            )
            return None
        return _generated_runtime_chapter(
            chapter.chapter_id,
            list(playable.segments),
            base_order=chapter_start_order,
        )


def _pending_narration_placeholder(
    chapter_id: str,
    *,
    planned_duration_seconds: int,
) -> NarrationSegment:
    """Reserve an unfrozen host seam without putting Writer/TTS on FastStart."""

    return NarrationSegment(
        id=f"{chapter_id}:narration:pending",
        chapter_id=chapter_id,
        order=0,
        state=SegmentState.PLANNED,
        planned_duration_seconds=max(1, planned_duration_seconds),
        title="Pending host bridge",
    )


def _generated_runtime_chapter(
    chapter_id: str,
    segments: Sequence[MusicSegment | NarrationSegment],
    *,
    base_order: int,
) -> GeneratedChapter:
    kind_counts: dict[SegmentKind, int] = {
        SegmentKind.MUSIC: 0,
        SegmentKind.NARRATION: 0,
    }
    normalized: list[MusicSegment | NarrationSegment] = []
    for offset, segment in enumerate(segments):
        kind_index = kind_counts[segment.kind]
        kind_counts[segment.kind] += 1
        normalized.append(
            segment.model_copy(
                update={
                    "id": f"{chapter_id}:{segment.kind.value.lower()}:{kind_index}",
                    "chapter_id": chapter_id,
                    "order": base_order + offset,
                }
            )
        )
    return GeneratedChapter(chapter_id=chapter_id, segments=normalized)


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

    if settings.resolved_tts_provider == "mock":
        tts: TTSProvider = MockTTSProvider(storage)
    else:
        live_settings.credential_for("minimax")
        if not live_settings.minimax_tts_voice_id:
            raise ProviderConfigurationError("minimax TTS requires MINIMAX_TTS_VOICE_ID")
        tts = MiniMaxTTSProvider(live_settings, storage=storage, ledger=ledger)

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
    retrieval = MusicRetrievalService(music_registry)
    return LiveEpisodeAssemblyService(
        fast_path=fast_path,
        background_pipeline=background_pipeline,
        retrieval=retrieval,
        composer=EpisodeComposer(music_registry),
        materializer=NarrationMaterializer(tts, storage),
        ledger=ledger,
        catalog_pool_builder=(
            CatalogPoolBuilder(retrieval, PoolBuildConfig(timeout_seconds=30.0))
            if settings.catalog_pool
            else None
        ),
        duration_scaling=settings.duration_scaling,
    )
