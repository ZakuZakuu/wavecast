"""Application-level assembly of a bounded, playable WaveCast episode.

The runtime and the intelligence services remain separate: this module is the
thin application seam that joins their provider-neutral contracts.  It never
promotes a proposal directly into playback; every chapter crosses the
deterministic catalog-resolution boundary first.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from pydantic import BaseModel, Field

from wavecast.composer import EpisodeComposer
from wavecast.intelligence.background import BackgroundIntelligencePipeline
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.fast_start import FastPathCoordinator, FastStartPlanner
from wavecast.intelligence.models import (
    ChapterPlan,
    FastResearchInput,
    FastStartPlan,
    NarrationScript,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
    RadioScript,
    RadioScriptBlock,
    RadioScriptBlockKind,
    ResolvedTrack,
    TrackProposal,
    UnresolvedTrackError,
)
from wavecast.intelligence.research import (
    BackgroundResearchService,
    FastResearchService,
)
from wavecast.intelligence.resolution import resolve_track_proposal_across_providers
from wavecast.intelligence.trace import GenerationTrace
from wavecast.intelligence.writer import WriterService
from wavecast.materialization import NarrationMaterializer
from wavecast.models.episode import NarrationSegment, PlayableEpisode, SegmentKind
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import (
    MusicProvider,
    ProgressiveLLMProvider,
    SearchProvider,
    TTSProvider,
)
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.fakes import (
    FakeSearchProvider,
    MockMusicProvider,
    MockTTSProvider,
)
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.providers.profiles import InferenceProfile, StructuredTransport
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.usage import UsageLedger, UsageTotals
from wavecast.storage.assets import LocalObjectStorageProvider


class EpisodeAssemblyError(RuntimeError):
    """A typed failure at one deterministic assembly boundary."""

    def __init__(self, message: str, *, stage: str) -> None:
        super().__init__(message)
        self.stage = stage


class LiveEpisodeAssemblyRequest(BaseModel):
    """Provider-neutral input for one bounded episode assembly run."""

    topic: str = Field(min_length=1, max_length=300)
    anchor_tracks: list[str] = Field(default_factory=list, max_length=8)
    desired_duration_seconds: int = Field(default=900, gt=0)
    max_tracks: int = Field(default=4, ge=2, le=8)
    listener_taste_context: str | None = Field(default=None, max_length=1000)


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
    trace: GenerationTrace


@dataclass(frozen=True)
class _ResolvedChapter:
    chapter: ChapterPlan
    writer_chapter: ChapterPlan
    track: ResolvedTrack


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
    ) -> None:
        self.fast_path = fast_path
        self.background_pipeline = background_pipeline
        self.retrieval = retrieval
        self.composer = composer
        self.materializer = materializer
        self.ledger = ledger or UsageLedger()

    async def assemble(
        self,
        request: LiveEpisodeAssemblyRequest,
        *,
        request_id: str | None = None,
    ) -> EpisodeAssemblyResult:
        started = perf_counter()
        request_id = request_id or uuid4().hex
        intelligence_input = FastResearchInput(
            topic=request.topic,
            anchor_tracks=list(request.anchor_tracks),
            desired_duration_seconds=request.desired_duration_seconds,
            listener_taste_context=request.listener_taste_context,
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
        try:
            skeleton = await self.background_pipeline.curator.curate(
                bundle,
                fast_result.plan,
                desired_duration_seconds=request.desired_duration_seconds,
            )
        except ProviderError as error:
            raise EpisodeAssemblyError(str(error), stage="curator") from error
        curator_ms = _elapsed_ms(curator_started)
        chapters = list(skeleton.chapters[: request.max_tracks])
        skeleton = skeleton.model_copy(update={"chapters": chapters})
        trace.mark("program_skeleton_ready", chapter_count=len(chapters))

        resolution_started = perf_counter()
        resolved_chapters: list[_ResolvedChapter] = []
        unresolved: list[UnresolvedAssemblyProposal] = []
        for chapter in chapters:
            try:
                resolved = await resolve_track_proposal_across_providers(
                    self.retrieval, chapter.track
                )
            except ProviderError as error:
                unresolved.append(
                    UnresolvedAssemblyProposal(
                        chapter_index=chapter.index,
                        proposal=chapter.track,
                        reason=f"resolution provider failed: {type(error).__name__}",
                    )
                )
                continue
            if resolved is None:
                unresolved.append(
                    UnresolvedAssemblyProposal(
                        chapter_index=chapter.index,
                        proposal=chapter.track,
                        reason="no exact playable catalog match",
                    )
                )
                continue
            resolved_chapters.append(
                _ResolvedChapter(
                    chapter=chapter,
                    writer_chapter=chapter.model_copy(
                        update={"index": len(resolved_chapters)}
                    ),
                    track=resolved,
                )
            )
        resolution_ms = _elapsed_ms(resolution_started)
        trace.mark(
            "tracks_resolved",
            resolved_count=len(resolved_chapters),
            unresolved_count=len(unresolved),
        )
        if len(resolved_chapters) < 2:
            raise EpisodeAssemblyError(
                f"assembly requires at least two resolved tracks; got {len(resolved_chapters)}",
                stage="resolution",
            )

        writer_started = perf_counter()
        writer_scripts: list[RadioScript | NarrationScript] = []
        previous_context = ""
        for index, resolved_chapter in enumerate(resolved_chapters):
            next_metadata = ""
            if index + 1 < len(resolved_chapters):
                next_track = resolved_chapters[index + 1].track
                next_metadata = f"{next_track.canonical_artist} — {next_track.canonical_title}"
            try:
                script = await self.background_pipeline.writer.write(
                    resolved_chapter.writer_chapter,
                    bundle.evidence,
                    previous_committed_context=previous_context,
                    next_track_metadata=next_metadata,
                )
            except ProviderError as error:
                raise EpisodeAssemblyError(str(error), stage="writer") from error
            writer_scripts.append(script)
            previous_context = _script_text(script)
        writer_ms = _elapsed_ms(writer_started)
        radio_script = _assemble_radio_script(writer_scripts, len(resolved_chapters))

        composition_started = perf_counter()
        try:
            playable_episode = await self.composer.compose(
                [item.track for item in resolved_chapters], radio_script
            )
        except (ProviderError, UnresolvedTrackError, ValueError) as error:
            raise EpisodeAssemblyError(str(error), stage="composition") from error
        composition_ms = _elapsed_ms(composition_started)

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
        return EpisodeAssemblyResult(
            playable_episode=playable_episode,
            fast_plan=fast_result.plan,
            skeleton=skeleton,
            resolved_tracks=[item.track for item in resolved_chapters],
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
            trace=trace,
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


def _script_text(script: RadioScript | NarrationScript) -> str:
    return script.text


def _script_blocks(script: RadioScript | NarrationScript) -> list[RadioScriptBlock]:
    if isinstance(script, RadioScript):
        return list(script.blocks)
    return [
        RadioScriptBlock(
            kind=RadioScriptBlockKind.TRANSITION,
            text=script.text,
            duration_seconds=script.intended_duration_seconds,
            tts_cues=list(script.tts_cues),
            evidence_ids=list(script.evidence_ids),
        )
    ]


def _assemble_radio_script(
    scripts: list[RadioScript | NarrationScript], track_count: int
) -> RadioScript:
    """Place chapter scripts once, preserving chapter order and gap semantics."""
    blocks: list[RadioScriptBlock] = []
    opening_intro_seen = False
    track_intro_targets: set[int] = set()
    transition_targets: set[int] = set()
    outro_added = False
    for chapter_index, script in enumerate(scripts):
        for block in _script_blocks(script):
            if block.kind is RadioScriptBlockKind.INTRO:
                # Only chapter zero owns the episode opening.  A later INTRO
                # is chapter-local narration, not a second opening anchor, and
                # is ignored until positional intro semantics exist.
                if chapter_index != 0 or opening_intro_seen:
                    continue
                opening_intro_seen = True
                blocks.append(block.model_copy(update={"track_index": None}))
            elif block.kind is RadioScriptBlockKind.TRACK_INTRO:
                target = block.track_index if block.track_index is not None else chapter_index
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
                target = block.track_index if block.track_index is not None else chapter_index
                if target < 0 or target >= track_count - 1 or target in transition_targets:
                    continue
                transition_targets.add(target)
                blocks.append(block.model_copy(update={"track_index": target}))
            elif block.kind is RadioScriptBlockKind.OUTRO:
                if chapter_index != track_count - 1 or outro_added:
                    continue
                outro_added = True
                blocks.append(block.model_copy(update={"track_index": None}))

    return RadioScript(
        blocks=blocks,
        evidence_ids=[evidence_id for script in scripts for evidence_id in _script_evidence_ids(script)],
        intended_duration_seconds=max(1, sum(block.intended_duration_seconds for block in blocks)),
    )


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
            blocks: list[RadioScriptBlock] = []
            if index == 0:
                blocks.append(
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.INTRO,
                        text="欢迎来到今晚的听歌路线。",
                        duration_seconds=5,
                    )
                )
            blocks.append(
                RadioScriptBlock(
                    kind=RadioScriptBlockKind.TRACK_INTRO,
                    text=f"现在进入第 {index + 1} 首。",
                    duration_seconds=4,
                )
            )
            if not _mock_next_track_metadata(prompt):
                blocks.append(
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.OUTRO,
                        text="这条路线先在这里收束。",
                        duration_seconds=5,
                    )
                )
            else:
                blocks.append(
                    RadioScriptBlock(
                        kind=RadioScriptBlockKind.TRANSITION,
                        text="接下来，我们把镜头推向更远的地方。",
                        duration_seconds=4,
                    )
                )
            return RadioScript(blocks=blocks, intended_duration_seconds=13)
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


def _build_music_registry(settings: ProviderSettings) -> MusicProviderRegistry:
    if settings.mode == "mock":
        provider = MockMusicProvider()
        return MusicProviderRegistry({"mock": provider}, preference=("mock",))

    providers: dict[str, MusicProvider] = {}
    from wavecast.providers.audius import AudiusMusicProvider
    from wavecast.providers.netease import NeteaseMusicProvider
    from wavecast.providers.qqmusic import QQMusicProvider

    if settings.netease_music_api_base_url:
        providers["netease"] = NeteaseMusicProvider(settings)
    if settings.qq_music_api_base_url:
        providers["qqmusic"] = QQMusicProvider(settings)
    if settings.audius_api_key or settings.audius_bearer_token:
        providers["audius"] = AudiusMusicProvider(settings)
    if not providers:
        raise ProviderConfigurationError(
            "live episode assembly requires at least one configured real music provider"
        )
    return MusicProviderRegistry(providers)


def create_episode_assembly_service(
    settings: ProviderSettings | None = None,
) -> LiveEpisodeAssemblyService:
    """Create the same assembly path in mock or explicitly configured live mode."""
    settings = settings or ProviderSettings.from_env()
    ledger = UsageLedger()
    music_registry = _build_music_registry(settings)
    storage = LocalObjectStorageProvider()
    if settings.mode == "mock":
        llm: ProgressiveLLMProvider = MockEpisodeAssemblyLLM()
        discovery: SearchProvider = FakeSearchProvider()
        research: SearchProvider = FakeSearchProvider()
        tts: TTSProvider = MockTTSProvider(storage)
    else:
        llm = DeepSeekLLMProvider(settings, ledger=ledger)
        discovery = ExaSearchProvider(settings, ledger=ledger)
        research = TavilySearchProvider(settings, ledger=ledger)
        tts = MiniMaxTTSProvider(settings, storage=storage, ledger=ledger)

    fast_research = FastResearchService(discovery=discovery, research=research, ledger=ledger)
    background_research = BackgroundResearchService(
        discovery=discovery, research=research, ledger=ledger
    )
    fast_path = FastPathCoordinator(
        research=fast_research,
        planner=FastStartPlanner(llm),
    )
    background_pipeline = BackgroundIntelligencePipeline(
        research=background_research,
        curator=CuratorService(llm),
        writer=WriterService(llm),
    )
    return LiveEpisodeAssemblyService(
        fast_path=fast_path,
        background_pipeline=background_pipeline,
        retrieval=MusicRetrievalService(music_registry),
        composer=EpisodeComposer(music_registry),
        materializer=NarrationMaterializer(tts, storage),
        ledger=ledger,
    )
