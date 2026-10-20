import asyncio
import hashlib
import json
import logging
import math
import os
import re
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any, Literal, cast
from urllib.parse import quote
from uuid import uuid4
from wave import open as open_wave

import httpx
from anyio import to_thread
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from wavecast.arrangement import MixPlan, plan_episode_mix
from wavecast.assembly import create_episode_assembly_service
from wavecast.auth import AuthPrincipal, AuthTokenError, JwksJWTVerifier
from wavecast.catalog_pool import CatalogPoolBuilder, PoolBuildConfig
from wavecast.deployment import audio_root_from_env, normalize_database_url
from wavecast.full_version import (
    MAX_CONCURRENT_FULL_VERSIONS,
    FullVersionStatus,
    full_version_progress,
    full_version_status,
    is_active,
    is_stale,
)
from wavecast.intelligence.research import FastResearchService
from wavecast.materialization import (
    MusicSnapshotError,
    MusicSnapshotStore,
    MusicSourceClassification,
    MusicSourceKind,
    NarrationMaterializer,
    ProviderPlaybackSnapshotFetcher,
    classify_music_source,
)
from wavecast.materialization.music import recoverable_music_source
from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    GenerationMode,
    LiveEpisode,
    MusicSegment,
    NarrationRole,
    NarrationSegment,
    PlayableEpisode,
    SegmentKind,
    SegmentState,
)
from wavecast.orchestration import (
    EpisodeOrchestrator,
    GenerationWorker,
    InlineGenerationScheduler,
)
from wavecast.orchestration.buffer import buffer_decision
from wavecast.orchestration.episode import EpisodeRuntimeError, InMemoryEpisodeRepository
from wavecast.orchestration.runtime import StagedProgressiveRuntimeAdapter
from wavecast.presentation import HostMode
from wavecast.proposals import (
    REASON_CATALOG_UNAVAILABLE,
    REASON_OPENING_NOT_FOUND,
    REASON_OPENING_UNPLAYABLE,
    DeterministicMockProgramProposalGenerator,
    InMemoryProgramProposalRepository,
    LLMProgramProposalGenerator,
    ProgramProposal,
    ProgramProposalBatch,
    ProgramProposalGenerationError,
    ProgramProposalGenerator,
    ProgramProposalRepository,
    ProposalGenerationRequest,
    ProposalPersistenceConflict,
)
from wavecast.providers.ark import ArkLLMProvider
from wavecast.providers.audius import AudiusMusicProvider
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import (
    AudioProvider,
    AudioSource,
    ObjectStorageProvider,
    ProgressiveLLMProvider,
    TTSProvider,
)
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.dialogue_voicing import build_dialogue_voicing
from wavecast.providers.doubao_podcast import PodcastTransport
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.factory import build_music_registry
from wavecast.providers.fakes import MockAudioProvider
from wavecast.providers.music_http import SidecarMusicProvider
from wavecast.providers.netease import NeteaseMusicProvider
from wavecast.providers.playback import ResolvedPlaybackRequest
from wavecast.providers.qqmusic import QQMusicProvider
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.providers.tts_factory import build_tts_provider
from wavecast.providers.usage import (
    UsageEvent,
    UsageLedger,
    cost_summary,
    diagnostics_of,
    merge_events,
    usage_scope,
)
from wavecast.public_shelf import PublicShelf
from wavecast.publication_service import PublicationService
from wavecast.publishing import (
    ProgrammeSnapshot,
    Publication,
    PublicationStatus,
    PublishRefusal,
    Visibility,
    is_publication_id,
    published_budget_bytes,
)
from wavecast.recommendations import (
    DeterministicRecommendationPlanner,
    InMemoryProgramIdeaRepository,
    ProgramIdeaRepository,
    ProgramIdeaResponse,
    ProviderBackedRecommendationPlanner,
    RecommendationPlanner,
    RecommendationService,
    UserContextAggregator,
)
from wavecast.rendering import (
    MixdownArtifact,
    MixRenderError,
    MixRendererUnavailableError,
    MixSourceUnavailableError,
    ProgramImmutabilityError,
    ProgramRenderManifest,
    frozen_prefix_is_compatible,
    hls_playlist,
    load_program_manifest,
    render_mix,
    render_program_prefix,
    resolve_mix_sources,
)
from wavecast.rendering.fingerprint import mix_plan_fingerprint
from wavecast.rendering.programme import DEFAULT_RENDER_HOLDBACK_SECONDS
from wavecast.spoken_form import KnownTrack, to_spoken_form
from wavecast.stations import StationId
from wavecast.storage import (
    EpisodeConcurrencyError,
    GenerationJobMode,
    GenerationJobRepository,
    GenerationJobStatus,
    GenerationQuotaRepository,
    InMemoryGenerationJobRepository,
    InMemoryGenerationQuotaRepository,
    InMemoryPublicationRepository,
    InMemoryUserLibraryRepository,
    LocalObjectStorageProvider,
    PostgresEpisodeRepository,
    PostgresGenerationJobRepository,
    PostgresGenerationQuotaRepository,
    PostgresPublicationRepository,
    PostgresUserLibraryRepository,
    PublicationRepository,
    QuotaExceededError,
    UserLibraryRepository,
)
from wavecast.storage.episodes import EpisodeRepository
from wavecast.storage.recommendations import PostgresProgramIdeaRepository
from wavecast.storage.usage_events import UsageEventStore
from wavecast.storage.user_context import (
    PostgresUserEventRepository,
    PostgresUserPreferencesRepository,
)
from wavecast.user_context import (
    AvoidArtistInput,
    InMemoryUserEventRepository,
    InMemoryUserPreferencesRepository,
    UserEvent,
    UserEventInput,
    UserEventRepository,
    UserEventService,
    UserPreferences,
    UserPreferencesRepository,
    UserPreferencesUpdate,
    with_avoided_artist,
    without_avoided_artist,
)

logger = logging.getLogger(__name__)

# Longest the first request of an episode waits for the opening host's TTS.
_OPENING_HOST_BUDGET_SECONDS = 8.0


def _configure_logging() -> None:
    """Make the counts-only ``wavecast.*`` INFO diagnostics visible in the API log."""

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s"
        )
    logging.getLogger("wavecast").setLevel(os.getenv("WAVECAST_LOG_LEVEL", "INFO").upper())


_configure_logging()

LISTENER_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
DATABASE_URL = os.getenv("WAVECAST_DATABASE_URL")
if DATABASE_URL:
    DATABASE_URL = normalize_database_url(DATABASE_URL)
AUDIO_ROOT = audio_root_from_env()
audio_storage: ObjectStorageProvider = LocalObjectStorageProvider(AUDIO_ROOT)
_provider_settings = ProviderSettings.from_env()
proposal_repository: ProgramProposalRepository = InMemoryProgramProposalRepository()
user_library_repository: UserLibraryRepository = InMemoryUserLibraryRepository()
generation_quota_repository: GenerationQuotaRepository = InMemoryGenerationQuotaRepository()
generation_job_repository: GenerationJobRepository = InMemoryGenerationJobRepository()
publication_repository: PublicationRepository = InMemoryPublicationRepository()
if DATABASE_URL:
    from wavecast.storage import PostgresProgramProposalRepository

    proposal_repository = PostgresProgramProposalRepository(DATABASE_URL)
    user_library_repository = PostgresUserLibraryRepository(DATABASE_URL)
    generation_quota_repository = PostgresGenerationQuotaRepository(DATABASE_URL)
    generation_job_repository = PostgresGenerationJobRepository(DATABASE_URL)
    publication_repository = PostgresPublicationRepository(DATABASE_URL)

GUEST_PROGRAM_LIMIT = int(os.getenv("WAVECAST_GUEST_PROGRAM_LIMIT", "3"))
AUTH_DAILY_PROGRAM_LIMIT = int(os.getenv("WAVECAST_AUTH_DAILY_PROGRAM_LIMIT", "20"))
GLOBAL_DAILY_PROGRAM_LIMIT = int(os.getenv("WAVECAST_GLOBAL_DAILY_PROGRAM_LIMIT", "100"))
# Published audio is kept for good, so it has a budget of its own (a share of the volume unless set).
_published_budget_mb = os.getenv("WAVECAST_PUBLISHED_AUDIO_BUDGET_MB", "").strip()
PUBLISHED_AUDIO_BUDGET_BYTES = int(_published_budget_mb) * 1024 * 1024 if _published_budget_mb else None
# Programmes switched off by hand (ids, comma separated): not listed, no new copies, no playback.
TAKEN_DOWN_PROGRAMMES = frozenset(
    item.strip() for item in os.getenv("WAVECAST_TAKEN_DOWN_PROGRAMMES", "").split(",") if item.strip()
)

# Programme HLS is a rebuildable cache. Keep enough headroom on the small
# Railway volume for source snapshots/TTS instead of allowing old renders to
# consume the filesystem.
PROGRAM_RENDER_GC_LOW_WATERMARK_BYTES = 120 * 1024 * 1024
PROGRAM_RENDER_GC_TARGET_FREE_BYTES = 200 * 1024 * 1024
if min(GUEST_PROGRAM_LIMIT, AUTH_DAILY_PROGRAM_LIMIT, GLOBAL_DAILY_PROGRAM_LIMIT) < 0:
    raise RuntimeError("generation quota limits must be non-negative")

user_preferences_repository: UserPreferencesRepository = (
    PostgresUserPreferencesRepository(DATABASE_URL)
    if DATABASE_URL
    else InMemoryUserPreferencesRepository()
)
_user_event_repository: UserEventRepository = (
    PostgresUserEventRepository(DATABASE_URL) if DATABASE_URL else InMemoryUserEventRepository()
)
user_event_service = UserEventService(_user_event_repository)
recommendation_repository: ProgramIdeaRepository = (
    PostgresProgramIdeaRepository(DATABASE_URL)
    if DATABASE_URL
    else InMemoryProgramIdeaRepository()
)


def _gc_program_render_cache(current_episode_id: str) -> tuple[int, int | None]:
    """Reclaim rebuildable audio caches, never active sources or paid narration."""

    root = Path(AUDIO_ROOT)
    try:
        usage = shutil.disk_usage(root)
    except OSError as error:
        logger.warning(
            "program_render_gc_disk_usage_failed root=%s error=%s",
            root,
            str(error),
        )
        return 0, None

    if usage.free >= PROGRAM_RENDER_GC_LOW_WATERMARK_BYTES:
        return 0, usage.free

    safe_current_episode_id = re.sub(r"[^a-zA-Z0-9_-]", "_", current_episode_id)
    protected_ids = {safe_current_episode_id}
    protected_music: set[str] = set()
    now = datetime.now(UTC).timestamp()
    # A stale is_listener_active flag alone must not pin abandoned caches.
    try:
        episodes = repository.all()
    except Exception:
        logger.warning("program_render_gc_protection_unavailable")
        return 0, usage.free
    try:
        # Published audio is what listeners' copies play; it is never a cache.
        protected_ids |= {
            re.sub(r"[^a-zA-Z0-9_-]", "_", episode_id)
            for episode_id in publication_repository.pinned_episode_ids()
        }
    except Exception:
        logger.warning("program_render_gc_publications_unavailable")
        return 0, usage.free
    for episode in episodes:
        if episode.id != current_episode_id and (
            not episode.is_listener_active
            or now - episode.last_heartbeat_at.timestamp() > 120
        ):
            continue
        protected_ids.add(re.sub(r"[^a-zA-Z0-9_-]", "_", episode.id))
        for segment in episode.timeline_segments:
            if segment.kind is SegmentKind.MUSIC:
                source = classify_music_source(segment.audio_source_url or "")
                if source.kind is MusicSourceKind.OWNED_ASSET:
                    protected_music.add(source.identity)

    # Old failed atomic writes are not published assets. Avoid in-flight writes
    # and preserve sidecar metadata (.json) needed to recover evicted music.
    for path in root.rglob(".*"):
        try:
            if (
                path.is_file() and re.fullmatch(r"\..+\.[a-zA-Z0-9_]{8}", path.name)
                and now - path.stat().st_mtime > 300
            ):
                path.unlink(missing_ok=True)
        except OSError:
            continue

    cache_root = root / "program-renders"
    candidates: list[tuple[float, Path]] = []
    try:
        for child in cache_root.iterdir() if cache_root.is_dir() else []:
            if not child.is_dir() or child.name in protected_ids:
                continue
            try:
                candidates.append((child.stat().st_mtime, child))
            except OSError:
                continue
    except OSError as error:
        logger.warning(
            "program_render_gc_scan_failed root=%s error=%s",
            cache_root,
            str(error),
        )
        return 0, usage.free

    deleted = 0
    free_bytes: int | None = usage.free
    for _mtime, candidate in sorted(candidates, key=lambda item: item[0]):
        try:
            shutil.rmtree(candidate)
            deleted += 1
        except FileNotFoundError:
            continue
        except OSError as error:
            logger.warning(
                "program_render_gc_delete_failed path=%s error=%s",
                candidate,
                str(error),
            )
            continue

        try:
            free_bytes = shutil.disk_usage(root).free
        except OSError:
            free_bytes = None
            break
        if free_bytes >= PROGRAM_RENDER_GC_TARGET_FREE_BYTES:
            break

    # Source snapshots previously had no GC at all. Keep their tiny recovery
    # metadata and evict bytes only when a validated provider identity exists.
    source_deleted = 0
    local_storage = LocalObjectStorageProvider(root)
    music_root = root / "music"
    sources: list[tuple[float, Path]] = []
    for path in music_root.rglob("*.audio"):
        try:
            sources.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(sources):
        free_bytes = shutil.disk_usage(root).free
        if free_bytes >= PROGRAM_RENDER_GC_TARGET_FREE_BYTES:
            break
        key = path.relative_to(root).as_posix()
        if key in protected_music:
            continue
        metadata = local_storage.metadata_for(key)
        if recoverable_music_source(metadata, key) is None:
            continue
        try:
            # Pin old snapshots before eviction too: a provider must never
            # silently replace historical programme audio on a later refetch.
            if not metadata.get("content_sha256"):
                with path.open("rb") as handle:
                    metadata["content_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
                sidecar = path.with_name(f".{path.name}.json")
                payload = json.loads(sidecar.read_text())
                payload["metadata"] = metadata
                local_storage._atomic_write(sidecar, json.dumps(payload).encode())
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            continue
        source_deleted += 1
    free_bytes = shutil.disk_usage(root).free
    logger.warning(
        "program_render_gc episode_id=%s deleted=%s source_deleted=%s free_bytes=%s",
        current_episode_id,
        deleted,
        source_deleted,
        free_bytes,
    )
    return deleted, free_bytes


def _program_render_free_bytes() -> int | None:
    try:
        return shutil.disk_usage(Path(AUDIO_ROOT)).free
    except OSError:
        return None


def _build_recommendation_planner(settings: ProviderSettings) -> RecommendationPlanner:
    mode = os.getenv("WAVECAST_RECOMMENDATION_PLANNER", "deterministic").strip().lower()
    if mode == "deterministic":
        return DeterministicRecommendationPlanner()
    if mode not in {"deepseek", "ark"}:
        raise ProviderConfigurationError(
            "WAVECAST_RECOMMENDATION_PLANNER must be deterministic, deepseek or ark"
        )

    # Recommendation inference is an independently gated capability.  It may use
    # a live model while episode assembly, TTS, and music providers remain in mock
    # mode, so enabling personalized ideas does not implicitly enable paid
    # generation elsewhere.  Ark shares the proposal role's model (ARK_PROPOSAL_MODEL)
    # with the on-demand proposal generator; the two keep their own prompts and modes.
    recommendation_settings = settings.for_live_capability()
    ledger = UsageLedger()
    if mode == "ark":
        recommendation_settings.credential_for("ark")
        ark_model = recommendation_settings.ark_model_for("proposal")
        return ProviderBackedRecommendationPlanner(
            lambda: ArkLLMProvider(
                recommendation_settings, model=ark_model, role="proposal", ledger=ledger
            ),
            source="ark_planner",
        )
    recommendation_settings.credential_for("deepseek")
    return ProviderBackedRecommendationPlanner(
        lambda: DeepSeekLLMProvider(recommendation_settings, ledger=ledger)
    )


recommendation_planner = _build_recommendation_planner(_provider_settings)

_auth_jwks_url = os.getenv("WAVECAST_AUTH_JWKS_URL")
_auth_issuer = os.getenv("WAVECAST_AUTH_ISSUER")
_auth_audience = os.getenv("WAVECAST_AUTH_AUDIENCE")
_auth_verifier = (
    JwksJWTVerifier(_auth_jwks_url, _auth_issuer, _auth_audience)
    if _auth_jwks_url and _auth_issuer and _auth_audience
    else None
)


def _provider_error_summary(error: Exception) -> str:
    """Error class and the adapter's already-sanitized message, for the operator's log."""

    return f"{type(error).__name__}: {str(error)[:200]}"


def _build_proposal_generator(
    settings: ProviderSettings, ledger: UsageLedger,
    *, opening_research: FastResearchService | None = None,
) -> ProgramProposalGenerator:
    """``ledger`` is the shared one: a proposal's calls are recorded (under the proposal's own id,
    before any episode exists) and persisted like the episode's, instead of in a private ledger."""

    if settings.resolved_proposal_planner == "mock":
        return DeterministicMockProgramProposalGenerator()
    live_settings = settings.for_live_capability()
    if settings.resolved_proposal_planner == "ark":
        proposal_llm: ProgressiveLLMProvider = ArkLLMProvider(
            live_settings,
            model=live_settings.ark_model_for("proposal"),
            role="proposal",
            ledger=ledger,
        )
    else:
        live_settings.credential_for("deepseek")
        proposal_llm = DeepSeekLLMProvider(live_settings, ledger=ledger)
    retrieval = MusicRetrievalService(build_music_registry(settings))
    return LLMProgramProposalGenerator(
        proposal_llm,
        retrieval,
        opening_research=(
            FastResearchService(
                discovery=opening_research.discovery,
                research=opening_research.research,
                ledger=ledger,
                deadline_seconds=3.0,
                research_label=opening_research.research_label,
            )
            if opening_research is not None and settings.resolved_research_provider != "mock"
            else None
        ),
        pool_builder=(
            CatalogPoolBuilder(
                retrieval,
                PoolBuildConfig(max_verifications=12, concurrency=2, timeout_seconds=20.0),
            )
            if settings.catalog_pool
            else None
        ),
    )


repository: EpisodeRepository = (
    PostgresEpisodeRepository(DATABASE_URL) if DATABASE_URL else InMemoryEpisodeRepository()
)


def _build_tts_provider(
    settings: ProviderSettings, storage: ObjectStorageProvider, ledger: UsageLedger
) -> TTSProvider:
    """``ledger`` is the shared one the usage endpoint reads; a provider with a ledger of its own
    keeps the opening host's voice out of the episode's report."""

    return build_tts_provider(settings, storage, ledger)


class BrowserProxyAudioProvider:
    """Expose provider-qualified music through same-origin WaveCast proxy routes."""

    def __init__(self, fallback: MockAudioProvider | None = None) -> None:
        self.fallback = fallback or MockAudioProvider()

    def music_source(self, track_ref: str) -> AudioSource:
        fallback_source = self.fallback.music_source(track_ref)
        provider_name, separator, track_id = track_ref.partition(":")
        if not separator or not track_id:
            return fallback_source

        encoded_id = quote(track_id, safe="")
        if provider_name in {"netease", "qqmusic"}:
            return AudioSource(
                source_url=f"/api/audio/sidecar/{provider_name}/{encoded_id}",
                duration_seconds=fallback_source.duration_seconds,
            )
        if provider_name == "audius":
            return AudioSource(
                source_url=f"/api/audio/audius/{encoded_id}",
                duration_seconds=fallback_source.duration_seconds,
            )
        return fallback_source

    def narration_source(
        self, segment_id: str, narration_text: str, duration_seconds: int
    ) -> AudioSource:
        return self.fallback.narration_source(
            segment_id, narration_text, duration_seconds
        )


def _build_audio_provider(settings: ProviderSettings) -> AudioProvider:
    if settings.resolved_music_provider == "mock":
        return MockAudioProvider()
    return BrowserProxyAudioProvider()


# Usage of calls made outside a progressive runtime (the single-segment endpoint with no runtime).
_api_usage_ledger = UsageLedger()


def _build_narration_materializer(
    settings: ProviderSettings,
    tts: TTSProvider,
    storage: ObjectStorageProvider,
    ledger: UsageLedger,
    *,
    transport: PodcastTransport | None = None,
) -> NarrationMaterializer:
    """The API's materializer; two-host voicing (when on) records into the *shared* ledger."""

    voicing = build_dialogue_voicing(settings, storage, ledger=ledger, transport=transport)
    return NarrationMaterializer(
        tts,
        storage,
        dialogue_speech=voicing.speech if voicing else None,
        dialogue_voices=voicing.voices if voicing else (),
        dialogue_speed=voicing.speed if voicing else None,
        dialogue_format=voicing.audio_format if voicing else None,
    )


def _build_progressive_runtime(
    settings: ProviderSettings, storage: ObjectStorageProvider
) -> StagedProgressiveRuntimeAdapter | None:
    if (
        settings.mode == "mock"
        and settings.resolved_music_provider != "mock"
        and not settings.has_live_progressive_intelligence
    ):
        return None
    try:
        return StagedProgressiveRuntimeAdapter(
            create_episode_assembly_service(settings, storage=storage)
        )
    except ProviderConfigurationError:
        if settings.mode == "live" or settings.has_live_episode_capability:
            raise
        return None


progressive_runtime = _build_progressive_runtime(_provider_settings, audio_storage)


def _usage_ledger() -> UsageLedger:
    """The ledger the usage endpoint reads: the runtime's, so every call is queryable there."""
    return progressive_runtime.assembly.ledger if progressive_runtime is not None else _api_usage_ledger


# Every scoped usage event is also kept in storage, so the per-episode report survives a restart.
_usage_event_store = UsageEventStore(audio_storage)
_usage_ledger().attach_sink(_usage_event_store)
# Built after the shared ledger exists, so the opening host's voice and the proposal planner
# record into it rather than into ledgers nobody reads.
_tts_provider = _build_tts_provider(_provider_settings, audio_storage, _usage_ledger())
proposal_generator: ProgramProposalGenerator | None = _build_proposal_generator(
    _provider_settings, _usage_ledger(),
    opening_research=progressive_runtime.assembly.fast_path.research if progressive_runtime else None,
)
narration_materializer = _build_narration_materializer(
    _provider_settings, _tts_provider, audio_storage, _usage_ledger()
)
audio_provider = _build_audio_provider(_provider_settings)
orchestrator = EpisodeOrchestrator(
    repository,
    audio_provider=audio_provider,
    progressive_runtime=progressive_runtime,
)
scheduler = InlineGenerationScheduler(orchestrator)
async def _prepare_first_listen(episode_id: str) -> None:
    """The start of a finished programme is mixed before it is called ready, so its first play is quick."""
    await _render_programme(episode_id)
    # A publication waiting for this episode's 完整版 can go on to its mix.
    await to_thread.run_sync(_advance_publication_for, episode_id)


generation_worker = GenerationWorker(
    generation_job_repository,
    orchestrator,
    worker_id=f"api-{uuid4().hex[:12]}",
    after_full_generation=_prepare_first_listen,
)
BACKGROUND_GENERATION_ENABLED = os.getenv(
    "WAVECAST_BACKGROUND_GENERATION_ENABLED",
    "1" if DATABASE_URL else "0",
).strip().lower() not in {"0", "false", "no", "off"}
_generation_worker_stop: asyncio.Event | None = None
_generation_worker_task: asyncio.Task[None] | None = None


async def _resolve_provider_playback_request(
    source: MusicSourceClassification,
) -> ResolvedPlaybackRequest:
    if source.kind is MusicSourceKind.SIDECAR_PROXY:
        provider_name, track_id = source.identity.split("/", 1)
        provider = _build_sidecar_provider(provider_name)
        try:
            return await provider.resolve_upstream_playback_request(
                f"{provider_name}:{track_id}"
            )
        finally:
            await provider.aclose()
    if source.kind is MusicSourceKind.AUDIUS_PROXY:
        audius_provider = _build_audius_provider()
        try:
            return await audius_provider.resolve_upstream_playback_request(source.identity)
        finally:
            await audius_provider.aclose()
    raise MusicSnapshotError("unsupported_music_source")


music_snapshot_store = MusicSnapshotStore(
    audio_storage, ProviderPlaybackSnapshotFetcher(_resolve_provider_playback_request)
)


def configure_runtime(
    episode_repository: EpisodeRepository,
    progressive_runtime_adapter: StagedProgressiveRuntimeAdapter | None = None,
) -> None:
    """Explicit injection seam for Postgres API integration tests and application setup."""
    global repository, orchestrator, scheduler, progressive_runtime, generation_worker
    repository = episode_repository
    if progressive_runtime_adapter is not None:
        progressive_runtime = progressive_runtime_adapter
    orchestrator = EpisodeOrchestrator(
        repository,
        audio_provider=audio_provider,
        progressive_runtime=progressive_runtime,
    )
    scheduler = InlineGenerationScheduler(orchestrator)
    generation_worker = GenerationWorker(
        generation_job_repository,
        orchestrator,
        worker_id=f"api-{uuid4().hex[:12]}",
        after_full_generation=_prepare_first_listen,
    )


def configure_music_snapshot_store(store: MusicSnapshotStore) -> None:
    """Injection seam for credential-free snapshot tests and deployments."""
    global music_snapshot_store
    if store.storage is not audio_storage:
        raise ValueError("music snapshot store must use the shared audio storage")
    music_snapshot_store = store


def configure_narration_materializer(materializer: NarrationMaterializer) -> None:
    """Injection seam for tests and deployments with alternate TTS/storage adapters."""
    global \
        audio_storage, \
        narration_materializer, \
        music_snapshot_store, \
        progressive_runtime, \
        orchestrator, \
        scheduler, \
        generation_worker
    narration_materializer = materializer
    audio_storage = materializer.storage
    progressive_runtime = _build_progressive_runtime(_provider_settings, audio_storage)
    music_snapshot_store = MusicSnapshotStore(
        audio_storage, ProviderPlaybackSnapshotFetcher(_resolve_provider_playback_request)
    )
    orchestrator = EpisodeOrchestrator(
        repository,
        audio_provider=audio_provider,
        progressive_runtime=progressive_runtime,
    )
    scheduler = InlineGenerationScheduler(orchestrator)
    generation_worker = GenerationWorker(
        generation_job_repository,
        orchestrator,
        worker_id=f"api-{uuid4().hex[:12]}",
        after_full_generation=_prepare_first_listen,
    )

app = FastAPI(title="Wavecast API", version="0.2.0")


@app.on_event("startup")
async def start_generation_worker() -> None:
    global _generation_worker_stop, _generation_worker_task
    await to_thread.run_sync(_gc_program_render_cache, "")
    if not BACKGROUND_GENERATION_ENABLED or _generation_worker_task is not None:
        return
    _generation_worker_stop = asyncio.Event()
    _generation_worker_task = asyncio.create_task(
        generation_worker.serve(_generation_worker_stop)
    )


@app.on_event("shutdown")
async def stop_generation_worker() -> None:
    global _generation_worker_stop, _generation_worker_task
    if _generation_worker_stop is not None:
        _generation_worker_stop.set()
    if _generation_worker_task is not None:
        await _generation_worker_task
    await generation_worker.stop_enrichment()
    _generation_worker_stop = None
    _generation_worker_task = None


_PROGRESSIVE_CATCHUP_RETRY_SECONDS = 90


def _queue_progressive_generation(
    episode: LiveEpisode,
    *,
    force: bool = False,
    retry_failed: bool = False,
) -> LiveEpisode:
    """Cheap scheduling signal; never execute provider work in the request path."""

    if (
        not episode.is_listener_active
        or episode.generation_mode is not GenerationMode.PROGRESSIVE
        or episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}
    ):
        return episode

    try:
        existing = generation_job_repository.get_for_episode(episode.id)
        if existing is not None:
            if existing.mode is GenerationJobMode.FULL:
                return episode
            if existing.status in {
                GenerationJobStatus.PENDING,
                GenerationJobStatus.RUNNING,
            }:
                return episode
            if (
                existing.status is GenerationJobStatus.FAILED
                and not retry_failed
            ):
                return episode

        needs_music = buffer_decision(
            episode,
            baseline_seconds=generation_worker.policy.target_ahead_seconds,
            max_chapters=generation_worker.policy.target_chapters,
        ).needs_generation
        needs_catchup = orchestrator.needs_progressive_catchup(episode)
        if (
            needs_music
            and orchestrator._ready_future_chapter_count(episode)
            >= generation_worker.policy.target_chapters
        ):
            # A publication backlog needs snapshot/render work, not another
            # paid generation job for already-prepared successor chapters.
            needs_music = False
        if not force and not needs_music and not needs_catchup:
            return episode

        if (
            not force
            and not needs_music
            and needs_catchup
            and existing is not None
            and existing.status is GenerationJobStatus.COMPLETED
            and (
                datetime.now(UTC) - existing.updated_at
            ).total_seconds() < _PROGRESSIVE_CATCHUP_RETRY_SECONDS
        ):
            # Catch-up may involve Research/Curator/Writer. Do not turn the
            # heartbeat into a paid polling loop when a recent attempt already
            # completed or deferred behind safe music.
            return episode

        queued = generation_job_repository.request(
            episode.id,
            GenerationJobMode.PROGRESSIVE,
        )
        logger.info(
            "generation_job_requested episode_id=%s status=%s mode=%s "
            "attempts=%s request_version=%s force=%s retry_failed=%s",
            episode.id,
            queued.status.value,
            queued.mode.value,
            queued.attempts,
            queued.request_version,
            force,
            retry_failed,
        )
    except Exception as error:
        # Playback stays authoritative even if queue persistence is temporarily
        # unavailable. Log only the exception type; provider/database payloads
        # and connection details must never enter application logs.
        logger.warning(
            "generation_job_queue_failed episode_id=%s error_type=%s",
            episode.id,
            type(error).__name__,
        )
    return episode


def _cancel_generation(episode_id: str) -> None:
    try:
        job = generation_job_repository.get_for_episode(episode_id)
        if job is not None and job.mode is GenerationJobMode.FULL:
            # Explicit full generation belongs to the Episode, not to the current
            # browser session. Leaving playback must not cancel preparation.
            return
        generation_job_repository.cancel_for_episode(episode_id)
    except Exception:
        pass


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def anonymous_listener(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    proposed = request.headers.get("x-wavecast-listener") or request.cookies.get(
        "wavecast_listener"
    )
    listener_id = proposed if proposed and LISTENER_PATTERN.fullmatch(proposed) else uuid4().hex
    request.state.listener_id = listener_id
    request.state.principal = AuthPrincipal(listener_id=listener_id)
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token.strip():
            return Response(status_code=401, content="Invalid bearer token")
        if _auth_verifier is None:
            return Response(status_code=503, content="Authentication is not configured")
        try:
            user_id = await _auth_verifier.verify(token.strip())
        except AuthTokenError:
            return Response(status_code=401, content="Invalid bearer token")
        request.state.principal = AuthPrincipal(listener_id=listener_id, user_id=user_id)
    response = await call_next(request)
    response.set_cookie("wavecast_listener", listener_id, httponly=True, samesite="lax")
    return response


SEEDS = [
    EpisodeSeed(
        id="city-pop-misunderstood",
        title="你可能一直误解了 City Pop",
        topic="City Pop 的夜行叙事与全球回流",
        short_description="从城市夜色里的律动出发，听见它如何跨越年代与海岸线。",
        estimated_duration_seconds=30 * 60,
        opening_track_ref="mock:opening",
        opening_track_title="Neon First Light",
        opening_track_artist="Mira Fields",
        cover=CoverParams(family="editorial", seed=213, palette=("#152238", "#ff6b6b")),
    ),
    EpisodeSeed(
        id="synthpop-return",
        title="从 Blinding Lights 出发，回到真正的 80s Synthpop",
        topic="合成器流行的明亮阴影",
        short_description="一条从当代流行回溯到合成器黄金年代的夜间路线。",
        estimated_duration_seconds=28 * 60,
        opening_track_ref="mock:opening",
        opening_track_title="Neon First Light",
        opening_track_artist="Mira Fields",
        cover=CoverParams(family="waveform", seed=414, palette=("#2b1649", "#55e6c1")),
    ),
]


class SeekRequest(BaseModel):
    position_seconds: int = Field(ge=0)


class ReplaceRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class BufferRequest(BaseModel):
    target_chapters: int = Field(default=2, ge=1, le=2)


class MaterializedEpisodeRequest(BaseModel):
    seed_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=500)
    estimated_duration_seconds: int = Field(gt=0)
    playable_episode: PlayableEpisode


class PlaybackCheckpointRequest(BaseModel):
    position_seconds: int = Field(ge=0)


class ProgramPlaybackCheckpointRequest(BaseModel):
    position_seconds: float = Field(ge=0)


class LibraryMergeRequest(BaseModel):
    library: dict[str, Any]


class LibraryRecentRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    episode_id: str = Field(alias="episodeId", min_length=1, max_length=128)
    seed_id: str = Field(alias="seedId", min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    topic: str | None
    current_title: str | None = Field(alias="currentTitle")
    updated_at: int = Field(alias="updatedAt", ge=0)
    progress_seconds: float = Field(alias="progressSeconds", ge=0)
    duration_seconds: float = Field(alias="durationSeconds", ge=0)


class LibrarySavedRecord(LibraryRecentRecord):
    saved_at: int = Field(alias="savedAt", ge=0)


class BlockedMusicSource(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    segment_id: str = Field(alias="segmentId")
    source_kind: MusicSourceKind = Field(alias="sourceKind")
    reason_code: str = Field(alias="reasonCode")


class MixdownPreparationResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    episode_id: str = Field(alias="episodeId")
    ready: bool
    owned_music_count: int = Field(alias="ownedMusicCount")
    snapshotted_music_count: int = Field(alias="snapshottedMusicCount")
    reused_music_count: int = Field(alias="reusedMusicCount")
    blocked_sources: list[BlockedMusicSource] = Field(alias="blockedSources")


def listener(request: Request) -> str:
    return cast(str, request.state.listener_id)


def principal(request: Request) -> AuthPrincipal:
    return cast(AuthPrincipal, request.state.principal)


def require_user(request: Request) -> AuthPrincipal:
    actor = principal(request)
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return actor


def owned(episode_id: str, actor: AuthPrincipal) -> None:
    try:
        episode = orchestrator.get(episode_id)
        if episode.listener_id != actor.listener_id and (
            actor.user_id is None or episode.owner_user_id != actor.user_id
        ):
            raise EpisodeRuntimeError("episode does not belong to this listener")
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=404, detail="Episode not found") from error


def operate(episode_id: str, actor: AuthPrincipal, operation: Callable[[], LiveEpisode]) -> LiveEpisode:
    owned(episode_id, actor)
    try:
        return operation()
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


async def operate_async(
    episode_id: str,
    actor: AuthPrincipal,
    operation: Callable[[], Awaitable[LiveEpisode]],
) -> LiveEpisode:
    await to_thread.run_sync(owned, episode_id, actor)
    try:
        return await operation()
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "postgres" if DATABASE_URL else "mock"}

def authenticated_user(request: Request) -> str:
    user_id = principal(request).user_id
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@app.get("/api/user-preferences/me", response_model=UserPreferences)
def get_user_preferences(request: Request) -> UserPreferences:
    user_id = authenticated_user(request)
    return user_preferences_repository.get(user_id) or UserPreferences(user_id=user_id)


@app.put("/api/user-preferences/me", response_model=UserPreferences)
def put_user_preferences(
    request: Request, body: UserPreferencesUpdate
) -> UserPreferences:
    user_id = authenticated_user(request)
    existing = user_preferences_repository.get(user_id)
    preferences = UserPreferences(
        user_id=user_id,
        # The onboarding form does not carry the 少放这类 list; saving it must not erase it.
        avoid_artists=existing.avoid_artists if existing else [],
        **body.model_dump(),
    )
    return user_preferences_repository.save(preferences)


@app.post("/api/user-preferences/me/avoid-artists/remove", response_model=UserPreferences)
def stop_avoiding_artist(request: Request, body: AvoidArtistInput) -> UserPreferences:
    user_id = authenticated_user(request)
    current = user_preferences_repository.get(user_id) or UserPreferences(user_id=user_id)
    return user_preferences_repository.save(without_avoided_artist(current, body.artist))


@app.post("/api/user-preferences/me/avoid-artists", response_model=UserPreferences)
def avoid_artist(request: Request, body: AvoidArtistInput) -> UserPreferences:
    user_id = authenticated_user(request)
    current = user_preferences_repository.get(user_id) or UserPreferences(user_id=user_id)
    return user_preferences_repository.save(with_avoided_artist(current, body.artist))


@app.delete("/api/user-preferences/me", response_model=UserPreferences)
def delete_user_preferences(request: Request) -> UserPreferences:
    user_id = authenticated_user(request)
    user_preferences_repository.delete(user_id)
    return UserPreferences(user_id=user_id)


@app.post("/api/user-events", response_model=UserEvent, status_code=201)
def create_user_event(request: Request, body: UserEventInput) -> UserEvent:
    return user_event_service.record(user_id=authenticated_user(request), event=body)


def _public_program_for_context(program_id: str) -> ProgramProposal | None:
    seed = _static_seed(program_id)
    return ProgramProposal.from_episode_seed(seed) if seed is not None else None


def _recommendation_service() -> RecommendationService:
    aggregator = UserContextAggregator(
        user_preferences_repository,
        _user_event_repository,
        proposal_repository,
        public_program_lookup=_public_program_for_context,
    )
    return RecommendationService(
        aggregator,
        recommendation_planner,
        recommendation_repository,
    )


class RecommendationShelfResponse(BaseModel):
    """One shelf of ideas, and whether "换一批" can still offer something else."""

    ideas: list[ProgramIdeaResponse]
    has_more: bool


class NextShelfRequest(BaseModel):
    shown_ids: list[str] = Field(default_factory=list, max_length=12)


@app.get("/api/recommendations/me", response_model=list[ProgramIdeaResponse])
def list_recommendations(request: Request) -> list[ProgramIdeaResponse]:
    shelf = _recommendation_service().shelf_for_user(authenticated_user(request))
    return [ProgramIdeaResponse.from_idea(idea) for idea in shelf.ideas]


@app.post("/api/recommendations/me/next", response_model=RecommendationShelfResponse)
def next_recommendations(body: NextShelfRequest, request: Request) -> RecommendationShelfResponse:
    """换一批: ideas not shown yet; the daily generation cap bounds what this can cost."""

    shelf = _recommendation_service().next_shelf(authenticated_user(request), body.shown_ids)
    return RecommendationShelfResponse(
        ideas=[ProgramIdeaResponse.from_idea(idea) for idea in shelf.ideas],
        has_more=shelf.has_more,
    )


@app.post("/api/recommendations/me/refresh", response_model=list[ProgramIdeaResponse])
def refresh_recommendations(request: Request) -> list[ProgramIdeaResponse]:
    ideas = _recommendation_service().refresh_for_user(authenticated_user(request))
    return [ProgramIdeaResponse.from_idea(idea) for idea in ideas]


@app.post(
    "/api/recommendations/me/{idea_id}/program-proposal",
    response_model=ProgramProposalBatch,
)
async def materialize_recommendation(
    idea_id: str,
    request: Request,
) -> ProgramProposalBatch:
    user_id = authenticated_user(request)
    recommendation_service = _recommendation_service()

    async def restore_available() -> None:
        await to_thread.run_sync(
            recommendation_service.restore_available,
            user_id,
            idea_id,
        )

    current = await to_thread.run_sync(
        recommendation_service.get_for_user,
        user_id,
        idea_id,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    claimed = await to_thread.run_sync(
        recommendation_service.claim_for_materialization,
        user_id,
        idea_id,
    )
    if claimed is None:
        # Asked again for a recommendation that was already made into a programme (a reply that never
        # reached the phone, or a second tap): hand back that programme instead of an error.
        made_id = await to_thread.run_sync(
            user_library_repository.created_for_recommendation, user_id, idea_id,
        )
        made = await to_thread.run_sync(proposal_repository.get, made_id) if made_id else None
        if made is not None:
            return ProgramProposalBatch(proposals=[made])
        raise HTTPException(status_code=409, detail="Recommendation is no longer available")
    owner = principal(request)
    seed = claimed.to_proposal_seed()
    body = seed.request
    if proposal_generator is None:
        await restore_available()
        raise HTTPException(status_code=503, detail="Program proposal generation is not configured")

    try:
        reservations = await to_thread.run_sync(
            lambda: generation_quota_repository.reserve(
                owner.listener_id,
                owner.user_id,
                body.count,
                guest_limit=GUEST_PROGRAM_LIMIT,
                auth_daily_limit=AUTH_DAILY_PROGRAM_LIMIT,
                global_daily_limit=GLOBAL_DAILY_PROGRAM_LIMIT,
            )
        )
    except QuotaExceededError as error:
        await restore_available()
        if error.reason == "account_daily_limit":
            detail = "今天的调频次数已达上限，请明天再试。"
        else:
            detail = "今天的调频服务已达到使用上限，请稍后再试。"
        raise HTTPException(status_code=429, detail=detail) from error
    except BaseException:
        await restore_available()
        raise

    proposal_persisted = False
    try:
        proposals = await proposal_generator.generate(body)
        if len(proposals) != 1:
            raise ProgramProposalGenerationError("proposal_count_mismatch")
        proposal = claimed.apply_to_proposal(proposals[0])
        proposals = [proposal]
        await to_thread.run_sync(
            lambda: proposal_repository.save_many(
                proposals,
                owner_listener_id=owner.listener_id,
                owner_user_id=user_id,
                source="recommendation",
            )
        )
        proposal_persisted = True
        await to_thread.run_sync(
            generation_quota_repository.charge,
            reservations,
            [proposal.id],
        )
        await to_thread.run_sync(
            user_library_repository.put,
            user_id,
            "CREATED",
            proposal.id,
            {
                "id": proposal.id,
                "recommendationId": idea_id,
                "reason": claimed.reason,
            },
        )
        return ProgramProposalBatch(proposals=proposals)
    except ProgramProposalGenerationError as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        await restore_available()
        raise _proposal_failure_http_error(error) from error
    except ProviderError as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        await restore_available()
        logger.warning("program_proposal_provider_failed error=%s", _provider_error_summary(error))
        raise HTTPException(status_code=502, detail="Program proposal provider failed") from error
    except ProposalPersistenceConflict as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        await restore_available()
        raise HTTPException(status_code=409, detail="Program proposal could not be saved") from error
    except BaseException:
        if not proposal_persisted:
            await to_thread.run_sync(generation_quota_repository.release, reservations)
            await restore_available()
        raise



def _mock_wav(duration_seconds: int) -> bytes:
    """Render deterministic silence so the browser can exercise real audio events."""
    bounded_duration = max(1, min(duration_seconds, 300))
    buffer = BytesIO()
    with open_wave(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(8000)
        wav.writeframes(b"\x80" * (8000 * bounded_duration))
    return buffer.getvalue()


@app.get("/api/audio/mock/{kind}/{item_id:path}")
def mock_audio(kind: str, item_id: str, duration: int = 1) -> Response:
    if kind not in {"music", "narration"} or not item_id:
        raise HTTPException(status_code=404, detail="Mock audio source not found")
    return Response(
        content=_mock_wav(duration),
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/assets/audio/{asset_key:path}")
async def audio_asset(asset_key: str) -> Response:
    try:
        stored = await audio_storage.get(asset_key)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Audio asset not found") from error
    if stored is None:
        raise HTTPException(status_code=404, detail="Audio asset not found")
    return Response(
        content=stored.content,
        media_type=stored.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


def _build_audius_provider() -> AudiusMusicProvider:
    return AudiusMusicProvider(ProviderSettings.from_env())


def _build_sidecar_provider(provider_name: str) -> SidecarMusicProvider:
    settings = ProviderSettings.from_env()
    providers: dict[str, type[SidecarMusicProvider]] = {
        "netease": NeteaseMusicProvider,
        "qqmusic": QQMusicProvider,
    }
    provider_type = providers.get(provider_name)
    if provider_type is None:
        raise ProviderConfigurationError("sidecar music provider is not supported")
    return provider_type(settings)


_PLAYBACK_REQUEST_CACHE_TTL_SECONDS = 30.0
_PLAYBACK_REQUEST_CACHE_MAX_ENTRIES = 128
_playback_request_cache: dict[
    tuple[str, str],
    tuple[float, ResolvedPlaybackRequest],
] = {}


async def _resolve_sidecar_playback_request(
    provider_name: str, track_id: str
) -> ResolvedPlaybackRequest:
    key = (provider_name, track_id)
    now = monotonic()
    cached = _playback_request_cache.get(key)
    if cached is not None:
        expires_at, request = cached
        if expires_at > now:
            return request
        _playback_request_cache.pop(key, None)

    provider = _build_sidecar_provider(provider_name)
    try:
        if hasattr(provider, "resolve_upstream_playback_request"):
            resolved = await provider.resolve_upstream_playback_request(
                f"{provider_name}:{track_id}"
            )
        else:
            resolved = ResolvedPlaybackRequest(
                provider=provider_name,
                url=await provider.resolve_upstream_playback_url(
                    f"{provider_name}:{track_id}"
                ),
            )
    finally:
        await provider.aclose()

    # Provider URLs are server-only and may be signed/ephemeral. Keep only a
    # small, short-lived in-memory cache so preload + Range requests for the
    # same source do not repeat catalog/playback resolution.
    if len(_playback_request_cache) >= _PLAYBACK_REQUEST_CACHE_MAX_ENTRIES:
        expired = [
            cache_key
            for cache_key, (expires_at, _) in _playback_request_cache.items()
            if expires_at <= now
        ]
        for cache_key in expired:
            _playback_request_cache.pop(cache_key, None)
        if len(_playback_request_cache) >= _PLAYBACK_REQUEST_CACHE_MAX_ENTRIES:
            _playback_request_cache.pop(next(iter(_playback_request_cache)))
    _playback_request_cache[key] = (
        now + _PLAYBACK_REQUEST_CACHE_TTL_SECONDS,
        resolved,
    )
    return resolved


async def _resolve_sidecar_playback_url(provider_name: str, track_id: str) -> str:
    return (await _resolve_sidecar_playback_request(provider_name, track_id)).url


@app.get("/api/audio/sidecar/{provider_name}/{track_id:path}")
async def sidecar_audio(provider_name: str, track_id: str, request: Request) -> StreamingResponse:
    try:
        playback_request = await _resolve_sidecar_playback_request(
            provider_name, track_id
        )
    except ProviderConfigurationError as error:
        raise HTTPException(status_code=503, detail="Sidecar playback is not configured") from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail="Sidecar playback unavailable") from error

    settings = ProviderSettings.from_env()
    headers = {"Accept": "audio/mpeg", **playback_request.headers}
    for header_name in ("range", "if-range"):
        if value := request.headers.get(header_name):
            headers[header_name.title()] = value
    client = httpx.AsyncClient(timeout=settings.timeout_seconds, follow_redirects=True)
    if playback_request.params:
        upstream = await client.send(
            client.build_request(
                "GET",
                playback_request.url,
                params=playback_request.params,
                headers=headers,
            ),
            stream=True,
        )
    else:
        upstream = await client.send(
            client.build_request("GET", playback_request.url, headers=headers),
            stream=True,
        )
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail="Sidecar playback unavailable")

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {"Cache-Control": "private, max-age=60"}
    for header_name in ("accept-ranges", "content-range", "content-length"):
        if value := upstream.headers.get(header_name):
            response_headers[header_name.title()] = value
    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "audio/mpeg"),
        headers=response_headers,
    )


@app.get("/api/audio/audius/{track_id:path}")
async def audius_audio(track_id: str, request: Request) -> StreamingResponse:
    """Proxy Audius streams without putting backend credentials in the browser."""
    provider = _build_audius_provider()
    try:
        playback_request = await provider.resolve_upstream_playback_request(track_id)
    except ProviderConfigurationError as error:
        await provider.aclose()
        raise HTTPException(status_code=503, detail="Audius playback is not configured") from error
    await provider.aclose()

    headers = {"Accept": "audio/mpeg", **playback_request.headers}
    for header_name in ("range", "if-range"):
        if value := request.headers.get(header_name):
            headers[header_name.title()] = value

    settings = ProviderSettings.from_env()
    client = httpx.AsyncClient(timeout=settings.timeout_seconds, follow_redirects=True)
    upstream = await client.send(
        client.build_request(
            "GET", playback_request.url, params=playback_request.params, headers=headers
        ),
        stream=True,
    )
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=502, detail="Audius playback unavailable")

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {"Cache-Control": "private, max-age=60"}
    for header_name in ("accept-ranges", "content-range", "content-length"):
        if value := upstream.headers.get(header_name):
            response_headers[header_name.title()] = value
    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "audio/mpeg"),
        headers=response_headers,
    )


def _static_seed(program_id: str) -> EpisodeSeed | None:
    return next((candidate for candidate in SEEDS if candidate.id == program_id), None)


def _proposal_for_program(program_id: str, actor: AuthPrincipal | None = None) -> ProgramProposal | None:
    proposal = proposal_repository.get(program_id)
    if proposal is not None:
        owner = proposal_repository.get_owner(program_id)
        if actor is not None and owner is not None and (
            (owner[1] is not None and owner[1] == actor.user_id)
            or (owner[1] is None and owner[0] == actor.listener_id)
        ):
            return proposal
        return None
    seed = _static_seed(program_id)
    return ProgramProposal.from_episode_seed(seed) if seed is not None else None


@app.get("/api/seeds", response_model=list[EpisodeSeed])
def list_seeds() -> list[EpisodeSeed]:
    return SEEDS


@app.get("/api/programs/{program_id}", response_model=ProgramProposal)
def program(program_id: str, request: Request) -> ProgramProposal:
    proposal = _proposal_for_program(program_id, principal(request))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return proposal


class PublicProgramme(BaseModel):
    """What a programme link shows anyone who opens it: the promise, not the listener's prompt."""

    id: str
    title: str
    cover_title: str | None = None
    description: str
    estimated_duration_seconds: int
    station: StationId | None = None
    route: list[str]
    tags: list[str]
    opening_track_title: str
    opening_track_artist: str
    cover: CoverParams
    is_owner: bool
    #: A published programme: listeners play the programme itself, nothing is made for them.
    published: bool = False
    #: The author has stopped sharing it; only people who already hold a copy can still open it.
    revoked: bool = False


class LegacyProgrammeLink(Exception):
    """A link made before sharing meant the programme itself: it asked each visitor for a new one."""


def _public_published(publication: Publication, actor: AuthPrincipal) -> PublicProgramme:
    if publication.id in TAKEN_DOWN_PROGRAMMES:
        raise HTTPException(status_code=404, detail="Program not found")
    owner = _owns_publication(publication, actor)
    revoked = publication.status is PublicationStatus.REVOKED
    if publication.status not in {PublicationStatus.PUBLISHED, PublicationStatus.REVOKED}:
        # Being made or failed: only its owner has a use for the page.
        if not owner:
            raise HTTPException(status_code=404, detail="Program not found")
    elif revoked and not owner and _published_copy_of(publication, actor) is None:
        raise HTTPException(status_code=410, detail="revoked")
    snapshot = publication.programme
    return PublicProgramme(
        id=publication.id,
        title=snapshot.title,
        cover_title=snapshot.cover_title,
        description=snapshot.description,
        estimated_duration_seconds=snapshot.estimated_duration_seconds,
        station=snapshot.station,
        route=snapshot.route,
        tags=snapshot.tags,
        opening_track_title=snapshot.opening_track_title,
        opening_track_artist=snapshot.opening_track_artist,
        cover=snapshot.cover,
        is_owner=owner,
        published=True,
        revoked=revoked,
    )


def _public_programme(program_id: str, actor: AuthPrincipal) -> PublicProgramme | None:
    if is_publication_id(program_id):
        publication = publication_repository.get(program_id)
        return _public_published(publication, actor) if publication is not None else None
    stored = proposal_repository.get(program_id)
    seed = None if stored is not None else _static_seed(program_id)
    proposal = stored or (ProgramProposal.from_episode_seed(seed) if seed is not None else None)
    if proposal is None:
        return None
    owner = proposal_repository.get_owner(program_id) if stored is not None else None
    is_owner = seed is not None or (
        owner is not None
        and (
            (owner[1] is not None and owner[1] == actor.user_id)
            or (owner[1] is None and owner[0] == actor.listener_id)
        )
    )
    if not is_owner:
        # Someone else's own programme. Links to it used to hand every visitor a fresh copy; they
        # no longer open, and never quietly turn into one.
        raise LegacyProgrammeLink()
    tags = list(dict.fromkeys([*proposal.genre_tags, *proposal.mood_tags]))[:6]
    return PublicProgramme(
        id=proposal.id,
        title=proposal.title,
        cover_title=proposal.cover_title,
        description=proposal.short_description,
        estimated_duration_seconds=proposal.estimated_duration_seconds,
        station=proposal.station,
        # Built-in programmes carry a generic four-step outline that says nothing.
        route=list(proposal.editorial_route) if stored is not None else [],
        tags=tags,
        opening_track_title=proposal.opening_track_title,
        opening_track_artist=proposal.opening_track_artist,
        cover=proposal.cover,
        is_owner=is_owner,
    )


_SHORT_CODE = re.compile(r"^[0-9a-f]{10}$")


class ResolvedProgramme(BaseModel):
    id: str


@app.get("/api/programs/by-code/{code}", response_model=ResolvedProgramme)
def program_by_short_code(code: str) -> ResolvedProgramme:
    """The published programme behind a short link."""

    if not _SHORT_CODE.fullmatch(code):
        raise HTTPException(status_code=404, detail="Program not found")
    publication = publication_repository.get_by_code(code)
    if publication is not None:
        return ResolvedProgramme(id=publication.id)
    if proposal_repository.find_id_by_prefix(f"proposal-{code}") is not None:
        raise HTTPException(status_code=410, detail="legacy")
    raise HTTPException(status_code=404, detail="Program not found")


@app.get("/api/programs/{program_id}/public", response_model=PublicProgramme)
def public_program(program_id: str, request: Request) -> PublicProgramme:
    try:
        programme = _public_programme(program_id, principal(request))
    except LegacyProgrammeLink as error:
        raise HTTPException(status_code=410, detail="legacy") from error
    if programme is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return programme


@app.post("/api/programs/{program_id}/adopt", status_code=410)
async def adopt_program(program_id: str) -> None:
    """Sharing used to mean a fresh copy made for each visitor. It now means the programme itself
    (see ``POST /api/published/{id}/copy``); links of the old kind do not open and never fall back."""
    raise HTTPException(status_code=410, detail="legacy")


@app.post("/api/program-proposals", response_model=ProgramProposalBatch)
async def create_program_proposals(
    body: ProposalGenerationRequest, request: Request,
) -> ProgramProposalBatch:
    return await _make_proposals(body, principal(request))


async def _make_proposals(
    body: ProposalGenerationRequest, owner: AuthPrincipal,
) -> ProgramProposalBatch:
    if proposal_generator is None:
        raise HTTPException(status_code=503, detail="Program proposal generation is not configured")
    try:
        reservations = await to_thread.run_sync(
            lambda: generation_quota_repository.reserve(
                owner.listener_id, owner.user_id, body.count,
                guest_limit=GUEST_PROGRAM_LIMIT,
                auth_daily_limit=AUTH_DAILY_PROGRAM_LIMIT,
                global_daily_limit=GLOBAL_DAILY_PROGRAM_LIMIT,
            )
        )
    except QuotaExceededError as error:
        if error.reason == "guest_limit":
            detail = f"\u8bbf\u5ba2\u53ef\u4ee5\u5148\u521b\u5efa {GUEST_PROGRAM_LIMIT} \u6863\u8282\u76ee\u3002\u767b\u5f55\u540e\u53ef\u4ee5\u7ee7\u7eed\u8c03\u9891\uff0c\u5e76\u540c\u6b65\u4f60\u7684\u8282\u76ee\u5e93\u3002"
        elif error.reason == "account_daily_limit":
            detail = "\u4eca\u5929\u7684\u8c03\u9891\u6b21\u6570\u5df2\u8fbe\u4e0a\u9650\uff0c\u8bf7\u660e\u5929\u518d\u8bd5\u3002"
        else:
            detail = "\u4eca\u5929\u7684\u8c03\u9891\u670d\u52a1\u5df2\u8fbe\u5230\u4f7f\u7528\u4e0a\u9650\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002"
        raise HTTPException(status_code=429, detail=detail) from error
    try:
        proposals = await proposal_generator.generate(body)
        if len(proposals) != body.count:
            raise ProgramProposalGenerationError("proposal_count_mismatch")
        proposal_ids = [item.id for item in proposals]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ProgramProposalGenerationError("proposal_id_collision")
        try:
            await _usage_event_store.link_batch(proposal_ids)
        except Exception:  # noqa: BLE001 - the usage report is secondary; never fail a proposal for it
            logger.warning("usage_batch_link_failed proposals=%s", len(proposal_ids))
        await to_thread.run_sync(
            lambda: proposal_repository.save_many(
                proposals, owner_listener_id=owner.listener_id,
                owner_user_id=owner.user_id, source="tune",
            )
        )
        # A quota slot represents a successfully persisted dynamic program, not
        # merely a provider response that failed the application contract.
        await to_thread.run_sync(generation_quota_repository.charge, reservations, proposal_ids)
        if owner.user_id is not None:
            for item in proposals:
                await to_thread.run_sync(
                    user_library_repository.put,
                    owner.user_id,
                    "CREATED",
                    item.id,
                    {"id": item.id},
                )
        return ProgramProposalBatch(proposals=proposals)
    except ProgramProposalGenerationError as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        raise _proposal_failure_http_error(error) from error
    except ProviderError as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        logger.warning("program_proposal_provider_failed error=%s", _provider_error_summary(error))
        raise HTTPException(status_code=502, detail="Program proposal provider failed") from error
    except ProposalPersistenceConflict as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        raise HTTPException(status_code=409, detail="Program proposal could not be saved") from error
    except BaseException:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        raise


# Listener-facing guidance for failures whose cause we can tell apart.  Anything else keeps
# the generic English gateway detail, which the web client replaces with its own fallback.
_PROPOSAL_FAILURE_GUIDANCE: dict[str, tuple[int, str]] = {
    REASON_OPENING_UNPLAYABLE: (
        422,
        "没能找到可以播放的开场歌。这位艺人或这个主题的不少作品，可能因为版权暂时没有合适的音源。"
        "换个说法，或试试相近的艺人和风格。",
    ),
    REASON_OPENING_NOT_FOUND: (
        422,
        "没有找到和这个说法对得上的歌曲。检查一下写法，或换个更常见的名字试试。",
    ),
    REASON_CATALOG_UNAVAILABLE: (
        503,
        "音乐服务暂时不太稳定，请稍后再试。",
    ),
}


def _proposal_failure_http_error(error: ProgramProposalGenerationError) -> HTTPException:
    guidance = _PROPOSAL_FAILURE_GUIDANCE.get(error.reason)
    if guidance is not None:
        status_code, detail = guidance
        return HTTPException(status_code=status_code, detail=detail)
    return HTTPException(
        status_code=502,
        detail=f"Program proposal generation failed ({error.reason})",
    )


def _opening_host_budget_seconds() -> float:
    """How long starting an episode may wait for the opening host's voice."""

    raw = os.getenv("WAVECAST_OPENING_HOST_BUDGET_SECONDS", "").strip()
    try:
        value = float(raw) if raw else _OPENING_HOST_BUDGET_SECONDS
    except ValueError:
        return _OPENING_HOST_BUDGET_SECONDS
    return value if value > 0 else _OPENING_HOST_BUDGET_SECONDS


async def _prepare_opening_host(
    episode: LiveEpisode,
    seed: EpisodeSeed,
) -> LiveEpisode:
    """Materialize one proposal-owned opening host beat before first render."""

    text = seed.opening_narration_text
    if (
        not text
        or seed.presentation_intent.host_mode is HostMode.NONE
        or any(segment.id == "segment-opening-host" for segment in episode.segments)
        or len(episode.segments) != 1
        or episode.program_playback_position_seconds > 0
        or episode.playback_position_seconds > 0
    ):
        return episode

    spoken = to_spoken_form(
        text,
        [KnownTrack(artist=seed.opening_track_artist, title=seed.opening_track_title)],
    )
    if not spoken.ok:
        # The voice cannot read part of this line; the opening host is optional.
        logger.warning("opening_narration_skipped episode_id=%s reason=unspeakable_script", episode.id)
        return episode

    narration = NarrationSegment(
        id="segment-opening-host",
        chapter_id="chapter-1",
        order=1,
        state=SegmentState.SCRIPT_READY,
        planned_duration_seconds=8,
        title="Track Intro",
        narration_text=text,
        tts_text=spoken.tts_text if spoken.tts_text != text else None,
        narration_role=NarrationRole.INTRO,
    )
    try:
        materialized = await asyncio.wait_for(
            narration_materializer.materialize(narration),
            timeout=_opening_host_budget_seconds(),
        )
    except TimeoutError:
        # Starting the music matters more than the host's first words: the
        # opening track is published as one immutable stream on the first
        # render, so a voice that arrives later has nowhere to go. Do not make
        # the listener wait for a slow TTS provider (its own timeout is 20s).
        logger.warning(
            "opening_narration_skipped episode_id=%s reason=budget_exceeded budget_seconds=%s",
            episode.id,
            _opening_host_budget_seconds(),
        )
        return episode
    except Exception as error:
        # The opening host is a quality enhancement, never a playback gate.
        logger.warning(
            "opening_narration_skipped episode_id=%s error_type=%s",
            episode.id,
            type(error).__name__,
        )
        return episode

    try:
        return await to_thread.run_sync(
            orchestrator.attach_opening_narration,
            episode.id,
            materialized,
        )
    except EpisodeConcurrencyError:
        return await to_thread.run_sync(orchestrator.get, episode.id)


@app.post("/api/episodes/from-seed/{seed_id}", response_model=LiveEpisode)
async def create_episode(seed_id: str, request: Request) -> LiveEpisode:
    return await _start_episode(seed_id, principal(request))


async def _start_episode(seed_id: str, actor: AuthPrincipal) -> LiveEpisode:
    seed = _static_seed(seed_id)
    if seed is None:
        proposal = await to_thread.run_sync(_proposal_for_program, seed_id, actor)
        seed = proposal.to_episode_seed() if proposal is not None else None
    if seed is None:
        raise HTTPException(status_code=404, detail="Episode seed not found")
    try:
        episode = await to_thread.run_sync(
            orchestrator.start_or_resume,
            seed,
            actor.listener_id,
            actor.user_id,
        )
        # The opening host's voice is a cost of this episode, whoever is asking for it.
        with usage_scope(episode.id):
            episode = await _prepare_opening_host(episode, seed)
        return await to_thread.run_sync(
            lambda: _queue_progressive_generation(
                episode,
                force=True,
                retry_failed=True,
            )
        )
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode creation raced; retry") from error


@app.post("/api/episodes/from-materialized", response_model=LiveEpisode)
def import_materialized_episode(
    body: MaterializedEpisodeRequest, request: Request
) -> LiveEpisode:
    try:
        return orchestrator.import_materialized(
            seed_id=body.seed_id,
            title=body.title,
            topic=body.topic,
            estimated_duration_seconds=body.estimated_duration_seconds,
            playable_episode=body.playable_episode,
            listener_id=principal(request).listener_id,
            owner_user_id=principal(request).user_id,
        )
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode creation raced; retry") from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _library_episode_payload(
    episode: LiveEpisode, source: LibraryRecentRecord | LibrarySavedRecord,
) -> dict[str, Any]:
    payload = source.model_dump(by_alias=True)
    payload.update({
        "episodeId": episode.id,
        "seedId": episode.seed_id,
        "title": episode.title or "WaveCast",
        "topic": episode.topic,
        "durationSeconds": max(episode.timeline_duration_seconds, episode.program_estimated_duration_seconds),
        "progressSeconds": min(float(payload["progressSeconds"]), float(episode.generated_frontier_seconds)),
    })
    if episode.current_segment_id:
        try:
            payload["currentTitle"] = episode.segment(episode.current_segment_id).title
        except KeyError:
            payload["currentTitle"] = None
    return payload


def _proposal_belongs_to_actor(proposal_id: str, actor: AuthPrincipal) -> bool:
    owner = proposal_repository.get_owner(proposal_id)
    if owner is None:
        return False
    return (
        owner[1] == actor.user_id
        if owner[1] is not None
        else owner[0] == actor.listener_id
    )


@app.get("/api/me/library")
def get_my_library(request: Request) -> dict[str, Any]:
    actor = require_user(request)
    assert actor.user_id is not None
    return user_library_repository.snapshot(actor.user_id)


@app.post("/api/me/library/merge")
def merge_my_library(body: LibraryMergeRequest, request: Request) -> dict[str, Any]:
    actor = require_user(request)
    assert actor.user_id is not None
    incoming = body.library
    favorites = incoming.get("favoriteSeedIds", [])
    created = incoming.get("createdProgramIds", [])
    recents = incoming.get("recentPrograms", [])
    saved = incoming.get("savedEpisodes", [])
    safe_favorites: list[str] = []
    for item in favorites if isinstance(favorites, list) else []:
        if not isinstance(item, str):
            continue
        if _static_seed(item) is not None:
            safe_favorites.append(item)
        elif proposal_repository.claim_user(item, actor.listener_id, actor.user_id) or _proposal_belongs_to_actor(item, actor):
            safe_favorites.append(item)
    safe_created: list[str] = []
    for item in created if isinstance(created, list) else []:
        if isinstance(item, str) and (
            proposal_repository.claim_user(item, actor.listener_id, actor.user_id)
            or _proposal_belongs_to_actor(item, actor)
        ):
            safe_created.append(item)

    safe_recents: list[dict[str, Any]] = []
    for raw in recents if isinstance(recents, list) else []:
        try:
            item = LibraryRecentRecord.model_validate(raw)
            claimed = repository.claim_user(item.episode_id, actor.listener_id, actor.user_id)
            if not claimed and not repository.owned_by_user(item.episode_id, actor.user_id):
                continue
            episode = repository.get(item.episode_id)
            if episode.seed_id == item.seed_id:
                safe_recents.append(_library_episode_payload(episode, item))
        except (ValueError, KeyError):
            continue

    safe_saved: list[dict[str, Any]] = []
    for raw in saved if isinstance(saved, list) else []:
        try:
            item = LibrarySavedRecord.model_validate(raw)
            claimed = repository.claim_user(item.episode_id, actor.listener_id, actor.user_id)
            if not claimed and not repository.owned_by_user(item.episode_id, actor.user_id):
                continue
            episode = repository.get(item.episode_id)
            if episode.seed_id == item.seed_id and episode.state is EpisodeState.MATERIALIZED:
                safe_saved.append(_library_episode_payload(episode, item))
        except (ValueError, KeyError):
            continue

    filtered = {
        "version": 1,
        "favoriteSeedIds": safe_favorites,
        "recentPrograms": safe_recents,
        "savedEpisodes": safe_saved,
        "createdProgramIds": safe_created,
    }
    return user_library_repository.merge(actor.user_id, filtered)


@app.put("/api/me/library/favorites/{program_id}")
def add_my_favorite(program_id: str, request: Request) -> dict[str, Any]:
    actor = require_user(request)
    if _static_seed(program_id) is None and not _proposal_belongs_to_actor(program_id, actor):
        raise HTTPException(status_code=404, detail="Program not found")
    assert actor.user_id is not None
    return user_library_repository.put(actor.user_id, "FAVORITE", program_id, {"id": program_id})


@app.delete("/api/me/library/favorites/{program_id}")
def remove_my_favorite(program_id: str, request: Request) -> dict[str, Any]:
    actor = require_user(request)
    if _static_seed(program_id) is None and not _proposal_belongs_to_actor(program_id, actor):
        raise HTTPException(status_code=404, detail="Program not found")
    assert actor.user_id is not None
    return user_library_repository.delete(actor.user_id, "FAVORITE", program_id)


@app.put("/api/me/library/recents/{episode_id}")
def put_my_recent(episode_id: str, body: LibraryRecentRecord, request: Request) -> dict[str, Any]:
    actor = require_user(request)
    owned(episode_id, actor)
    episode = orchestrator.get(episode_id)
    if episode.owner_user_id is None and episode.listener_id == actor.listener_id:
        if repository.claim_user(episode_id, actor.listener_id, actor.user_id or ""):
            episode = orchestrator.get(episode_id)
    if body.episode_id != episode_id or body.seed_id != episode.seed_id:
        raise HTTPException(status_code=422, detail="Library item does not match episode")
    assert actor.user_id is not None
    payload = _library_episode_payload(episode, body)
    return user_library_repository.put(actor.user_id, "RECENT", episode_id, payload)


@app.delete("/api/me/library/recents/{episode_id}")
def delete_my_recent(episode_id: str, request: Request) -> dict[str, Any]:
    """Take one recent record out of the account's Library. The episode itself is untouched."""
    actor = require_user(request)
    assert actor.user_id is not None
    return user_library_repository.delete(actor.user_id, "RECENT", episode_id)


@app.put("/api/me/library/saved/{episode_id}")
def put_my_saved(episode_id: str, body: LibrarySavedRecord, request: Request) -> dict[str, Any]:
    actor = require_user(request)
    owned(episode_id, actor)
    episode = orchestrator.get(episode_id)
    if episode.owner_user_id is None and episode.listener_id == actor.listener_id:
        if repository.claim_user(episode_id, actor.listener_id, actor.user_id or ""):
            episode = orchestrator.get(episode_id)
    if episode.state is not EpisodeState.MATERIALIZED:
        raise HTTPException(status_code=409, detail="Only complete episodes can be saved")
    if body.episode_id != episode_id or body.seed_id != episode.seed_id:
        raise HTTPException(status_code=422, detail="Library item does not match episode")
    assert actor.user_id is not None
    payload = _library_episode_payload(episode, body)
    return user_library_repository.put(actor.user_id, "SAVED", episode_id, payload)


@app.delete("/api/me/library/saved/{episode_id}")
def delete_my_saved(episode_id: str, request: Request) -> dict[str, Any]:
    actor = require_user(request)
    assert actor.user_id is not None
    return user_library_repository.delete(actor.user_id, "SAVED", episode_id)


@app.get("/api/episodes/{episode_id}", response_model=LiveEpisode)
def episode(episode_id: str, request: Request) -> LiveEpisode:
    owned(episode_id, principal(request))
    return orchestrator.get(episode_id)


@app.get("/api/episodes/{episode_id}/usage")
async def episode_usage(episode_id: str, request: Request) -> dict[str, Any]:
    """Provider usage and a programme summary for one episode, without prompts or URLs.

    The events come from the running process and from storage (so a restart does not empty the
    report), each call once.  Costs are per currency, with the calls whose cost is unknown
    listed apart.  It is meant for reviewing a generation, not as a billing record.
    """

    # The episode repository is synchronous (Postgres runs it with asyncio.run), so it is read
    # off the event loop like everywhere else.
    await to_thread.run_sync(owned, episode_id, principal(request))
    current = await to_thread.run_sync(orchestrator.get, episode_id)
    ledger = _usage_ledger()
    await ledger.flush()
    try:
        stored = await _usage_event_store.load(episode_id)
    except ValueError:
        logger.warning("usage_events_unreadable episode_id=%s", episode_id)
        stored = []
    events = merge_events(ledger.for_scope(episode_id), stored)
    # What the proposal that started this episode cost.  Kept apart: it happened before the
    # episode existed, and it is not part of generating the programme.
    proposal_events: list[UsageEvent] = []
    batch_size = 1
    if current.seed_id:
        # Cards generated together share one call: its events sit under the batch's first id.
        try:
            proposal_scope, batch_size = await _usage_event_store.batch_scope(current.seed_id)
            proposal_stored = await _usage_event_store.load(proposal_scope)
        except ValueError:
            proposal_scope, batch_size, proposal_stored = current.seed_id, 1, []
        proposal_events = merge_events(ledger.for_scope(proposal_scope), proposal_stored)
    reporting = progressive_runtime is not None or bool(_api_usage_ledger.events) or bool(stored)
    segments = current.timeline_segments
    return {
        "episode_id": current.id,
        "programme": {
            "state": current.state.value,
            "estimated_duration_seconds": current.program_estimated_duration_seconds,
            "timeline_duration_seconds": current.timeline_duration_seconds,
            "music_segments": sum(1 for item in segments if item.kind is SegmentKind.MUSIC),
            "narration_segments": sum(1 for item in segments if item.kind is SegmentKind.NARRATION),
            "narration_skipped": sum(
                1
                for item in current.ordered_segments
                if item.kind is SegmentKind.NARRATION and item.state is SegmentState.SKIPPED
            ),
        },
        "providers": diagnostics_of(events, with_ids=True) if reporting else None,
        "costs": cost_summary(events) if reporting else None,
        "proposal": (
            {
                "providers": diagnostics_of(proposal_events, with_ids=True),
                "costs": cost_summary(proposal_events),
                # >1: the cost of one call that produced this many cards; counted once, not per card.
                "shared_by_proposals": batch_size,
            }
            if proposal_events
            else None
        ),
        "stored_events": len(stored),
    }


@app.get("/api/episodes/{episode_id}/evidence")
def episode_evidence(episode_id: str, request: Request) -> dict[str, Any]:
    """The evidence behind each chapter's narration, for checking what the host said.

    Source domain and title only (no full URLs, queries, prompts or raw responses), and only
    for the episode's owner.  An episode with no stored plan has none.
    """

    owned(episode_id, principal(request))
    current = orchestrator.get(episode_id)
    session = current.progressive_session
    if session is None:
        return {"episode_id": current.id, "chapters": [], "evidence": []}
    narration_by_chapter: dict[str, list[str]] = {}
    for segment in current.ordered_segments:
        if segment.kind is SegmentKind.NARRATION and segment.state is not SegmentState.SKIPPED:
            narration_by_chapter.setdefault(segment.chapter_id, []).append(segment.id)
    chapters = [
        {
            "chapter_id": item.chapter_id,
            "evidence_ids": list(item.chapter.evidence_ids),
            "narration_segment_ids": narration_by_chapter.get(item.chapter_id, []),
        }
        for item in session.chapters
    ]
    cited = {evidence_id for item in chapters for evidence_id in item["evidence_ids"]}
    evidence = [
        {
            "id": item.id,
            "claim": item.claim_or_excerpt[:400],
            "source_domain": item.source_domain,
            "source_title": item.source_title[:160],
            "source_provider": item.source_provider,
            "confidence": item.confidence,
        }
        for item in session.research.evidence
        if item.id in cited
    ]
    return {"episode_id": current.id, "chapters": chapters, "evidence": evidence}


def canonical_mix_plan_for_episode(episode_id: str, actor: AuthPrincipal) -> MixPlan:
    """Build the canonical arrangement for the currently ready timeline prefix."""
    current = orchestrator.get(episode_id)
    ready_segments: list[MusicSegment | NarrationSegment] = []
    for segment in current.timeline_segments:
        if segment.is_audio_ready:
            ready_segments.append(cast(MusicSegment | NarrationSegment, segment))
            continue
        if segment.kind is SegmentKind.NARRATION:
            # Narration is optional for continuity. Keep the arrangement usable
            # when a later music source is already ready.
            continue
        break
    if not ready_segments:
        raise ValueError("mix plan is not ready")
    return plan_episode_mix(PlayableEpisode(id=current.id, segments=ready_segments))


# A finished programme is rendered a few minutes at a time, from the start, instead of all at once: its
# first listen then starts in seconds, and the rest is added as the listener gets near the end of what
# is rendered (the same way a programme still being made grows). Whole segments only, as the renderer
# expects, and enough of them that what may be published (the plan less its held-back tail) reaches the
# wanted point.
PROGRAMME_RENDER_AHEAD_SECONDS = 300.0
_PROGRAMME_RENDER_MARGIN_SECONDS = 10.0
#: The songs of a little more than is rendered are fetched too, as their real lengths are only known then.
_PROGRAMME_FETCH_EXTRA_SECONDS = 120.0


def _ready_prefix(
    current: LiveEpisode, ahead_seconds: float | None = None,
) -> tuple[list[MusicSegment | NarrationSegment], bool]:
    """The ready, whole-segment prefix to render, and whether more ready segments were left out."""

    ready_segments: list[MusicSegment | NarrationSegment] = []
    for segment in current.timeline_segments:
        if segment.is_audio_ready:
            ready_segments.append(cast(MusicSegment | NarrationSegment, segment))
            continue
        if segment.kind is SegmentKind.NARRATION and (
            segment.state is SegmentState.SKIPPED
            or current.presentation_intent.host_mode is HostMode.NONE
        ):
            # A persisted SKIPPED state is an editorial decision and is safe to
            # freeze past. A merely pending narration is not.
            continue
        break
    if ahead_seconds is None:
        return ready_segments, False
    needed = ahead_seconds + DEFAULT_RENDER_HOLDBACK_SECONDS + _PROGRAMME_RENDER_MARGIN_SECONDS
    for count in range(1, len(ready_segments) + 1):
        plan = plan_episode_mix(PlayableEpisode(id=current.id, segments=ready_segments[:count]))
        if plan.duration_seconds >= needed:
            return ready_segments[:count], count < len(ready_segments)
    return ready_segments, False


def _canonical_render_plan(current: LiveEpisode, ahead_seconds: float | None = None) -> MixPlan:
    """Build the renderable prefix from one immutable Episode snapshot."""

    ready_segments, _ = _ready_prefix(current, ahead_seconds)
    if not ready_segments:
        raise ValueError("program render plan is not ready")
    return plan_episode_mix(PlayableEpisode(id=current.id, segments=ready_segments))


def canonical_render_plan_for_episode(episode_id: str) -> MixPlan:
    """Build only the prefix whose editorial inputs are safe to freeze.

    Unlike realtime fallback playback, the immutable programme renderer must not
    skip an unfinished host segment and then publish later music. A pending
    narration therefore closes the renderable prefix unless the programme is
    explicitly music-only.
    """

    return _canonical_render_plan(orchestrator.get(episode_id))


def _progressive_programme_ready_to_close(episode: LiveEpisode) -> bool:
    """A durable, exhausted route with settled host beats is a genuine ending."""
    session = episode.progressive_session
    if episode.generation_mode is not GenerationMode.PROGRESSIVE or session is None:
        return False
    if session.next_chapter(episode) is not None:
        return False
    authored = set(session.narration_authored_chapter_ids)
    if any(chapter.chapter_id not in authored for chapter in session.chapters):
        return False
    return all(
        segment.is_audio_ready
        or (
            segment.kind is SegmentKind.NARRATION
            and episode.presentation_intent.host_mode is HostMode.NONE
        )
        for segment in episode.timeline_segments
    )


def _finish_rendered_progressive_programme(episode_id: str, fingerprint: str) -> None:
    # Freeze lifecycle only after the immutable renderer has accepted the final
    # plan. Late-host recovery must still be possible before that acceptance.
    for _ in range(5):
        episode = repository.get(episode_id).model_copy(deep=True)
        if episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
            return
        if not _progressive_programme_ready_to_close(episode):
            return
        if mix_plan_fingerprint(_canonical_render_plan(episode)) != fingerprint:
            return
        if episode.presentation_intent.host_mode is HostMode.NONE:
            for segment in episode.timeline_segments:
                if segment.kind is SegmentKind.NARRATION and not segment.is_audio_ready:
                    segment.state = SegmentState.SKIPPED
        episode.state = EpisodeState.MATERIALIZED
        episode.last_activity_at = datetime.now(UTC)
        try:
            repository.save(episode)
            return
        except EpisodeConcurrencyError:
            continue


def _record_program_publication(episode_id: str, frontier: float, latency: float) -> None:
    for _ in range(5):
        episode = repository.get(episode_id).model_copy(deep=True)
        if episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
            return
        if episode.program_rendered_frontier_seconds == frontier:
            return
        episode.program_rendered_frontier_seconds = frontier
        episode.program_publication_latency_seconds = min(
            600, max(latency, episode.program_publication_latency_seconds * 0.8),
        )
        try:
            repository.save(episode)
            return
        except EpisodeConcurrencyError:
            continue


_CONTINUITY_SKIP_RUNWAY_SECONDS = 50.0


def _skip_blocking_optional_narration_for_continuity(
    episode_id: str,
    manifest: ProgramRenderManifest,
) -> list[str]:
    """Let ready music pass when optional narration is consuming the live buffer."""

    if manifest.complete:
        return []

    for attempt in range(5):
        episode = repository.get(episode_id).model_copy(deep=True)
        if (
            episode.generation_mode is not GenerationMode.PROGRESSIVE
            or episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}
        ):
            return []

        # Give the host time to arrive: skip only once the published audio the
        # listener can still reach is about to run out, not whenever the
        # refill buffer is below its ideal target.
        rendered_ahead = max(
            0.0,
            manifest.rendered_frontier_seconds
            - episode.program_playback_position_seconds,
        )
        if rendered_ahead >= _CONTINUITY_SKIP_RUNWAY_SECONDS:
            return []

        timeline = episode.timeline_segments
        skipped: list[str] = []
        for index, segment in enumerate(timeline):
            if (
                not isinstance(segment, NarrationSegment)
                or segment.id == "segment-opening-host"
                or segment.is_audio_ready
                or segment.state is SegmentState.SKIPPED
            ):
                continue
            later_ready_music = any(
                isinstance(later, MusicSegment) and later.is_audio_ready
                for later in timeline[index + 1 :]
            )
            if not later_ready_music:
                continue
            segment.state = SegmentState.SKIPPED
            skipped.append(segment.id)
            break

        if not skipped:
            return []

        episode.last_activity_at = datetime.now(UTC)
        try:
            repository.save(episode)
            return skipped
        except EpisodeConcurrencyError:
            if attempt < 4:
                continue
            raise
    return []


def _recover_late_optional_narration_for_frozen_prefix(
    episode_id: str,
    manifest: ProgramRenderManifest,
) -> list[str]:
    """Drop only narration whose removal exactly restores the frozen programme.

    Also for a programme whose full version is done (MATERIALIZED) but whose rendering stopped at a
    frozen prefix: narration that was written into that stretch after it had been rendered would
    otherwise keep the rest of it from being rendered, played or shared. Skipping exactly those
    narrations gives back the frozen timeline, so every position, subtitle and jump stays where the
    listener heard it. A programme already published is left alone.
    """

    if manifest.complete:
        return []

    for attempt in range(5):
        episode = repository.get(episode_id).model_copy(deep=True)
        finished = episode.state is EpisodeState.MATERIALIZED
        if episode.state is EpisodeState.PUBLISHED or (
            not finished and episode.generation_mode is not GenerationMode.PROGRESSIVE
        ):
            return []

        candidates = [
            segment
            for segment in reversed(episode.timeline_segments)
            if (
                isinstance(segment, NarrationSegment)
                and segment.id != "segment-opening-host"
                and segment.state is SegmentState.AUDIO_READY
                # What the finished programme marks as committed says nothing about what was heard.
                and (finished or not segment.is_committed)
            )
        ]
        if not candidates:
            return []

        retry = False
        for count in range(1, min(3, len(candidates)) + 1):
            for subset in combinations(candidates, count):
                working = episode.model_copy(deep=True)
                skipped_ids = [segment.id for segment in subset]
                for segment_id in skipped_ids:
                    candidate = working.segment(segment_id)
                    assert isinstance(candidate, NarrationSegment)
                    candidate.state = SegmentState.SKIPPED
                try:
                    plan = _canonical_render_plan(working)
                except ValueError:
                    continue
                if not frozen_prefix_is_compatible(plan, manifest):
                    continue

                working.last_activity_at = datetime.now(UTC)
                try:
                    repository.save(working)
                except EpisodeConcurrencyError:
                    retry = True
                    break
                return skipped_ids
            if retry:
                break
        if retry and attempt < 4:
            continue
        return []
    return []


async def _prepare_owned_music_assets(
    episode_id: str,
    *,
    ready_only: bool = False,
    only_segment_ids: Collection[str] | None = None,
) -> MixdownPreparationResult:
    """Snapshot provider-backed music before any deterministic server render.

    Progressive programme rendering must ignore music that is not audio-ready
    yet; otherwise speculative future slots with no playback URL would block the
    already-renderable prefix. Full mixdown keeps the previous all-music
    behavior.
    """

    for attempt in range(2):
        # PostgresEpisodeRepository intentionally exposes a synchronous
        # orchestrator boundary backed by asyncio.run(). This helper itself is
        # async because source snapshotting performs network I/O, so all
        # synchronous episode repository access must leave the request loop.
        current = await to_thread.run_sync(orchestrator.get, episode_id)
        working = current.model_copy(deep=True)
        updates: list[tuple[MusicSegment, str, str, int]] = []
        blocked: list[BlockedMusicSource] = []
        owned_count = 0
        snapshotted_count = 0
        reused_count = 0

        for segment in working.timeline_segments:
            if not isinstance(segment, MusicSegment):
                continue
            if ready_only and not segment.is_audio_ready:
                continue
            if only_segment_ids is not None and segment.id not in only_segment_ids:
                continue
            classification = classify_music_source(segment.audio_source_url or "")
            if classification.kind is MusicSourceKind.OWNED_ASSET:
                if (
                    isinstance(audio_storage, LocalObjectStorageProvider)
                    and audio_storage.exists(classification.identity)
                ):
                    owned_count += 1
                    continue
            if classification.kind is MusicSourceKind.UNSUPPORTED:
                blocked.append(
                    BlockedMusicSource(
                        segmentId=segment.id,
                        sourceKind=classification.kind,
                        reasonCode=classification.reason_code or "unsupported_music_source",
                    )
                )
                continue
            try:
                snapshot = await music_snapshot_store.snapshot(
                    classification,
                    track_ref=segment.track_ref,
                    duration_seconds=segment.duration_seconds,
                )
            except MusicSnapshotError as error:
                blocked.append(
                    BlockedMusicSource(
                        segmentId=segment.id,
                        sourceKind=classification.kind,
                        reasonCode=error.reason_code,
                    )
                )
                continue
            updates.append(
                (
                    segment,
                    snapshot.playback_url,
                    snapshot.asset_ref,
                    snapshot.duration_seconds,
                )
            )
            owned_count += 1
            if snapshot.reused:
                reused_count += 1
            else:
                snapshotted_count += 1

        result = MixdownPreparationResult(
            episodeId=episode_id,
            ready=not blocked,
            ownedMusicCount=owned_count,
            snapshottedMusicCount=snapshotted_count,
            reusedMusicCount=reused_count,
            blockedSources=blocked,
        )
        if blocked or not updates:
            return result

        for segment, playback_url, asset_ref, duration_seconds in updates:
            segment.audio_source_url = playback_url
            segment.asset_ref = asset_ref
            segment.actual_duration_seconds = duration_seconds
        try:
            await to_thread.run_sync(repository.save, working)
            return result
        except EpisodeConcurrencyError:
            if attempt == 0:
                continue
            raise

    raise EpisodeConcurrencyError(f"could not snapshot episode after retry: {episode_id}")


@app.get("/api/episodes/{episode_id}/mix-plan", response_model=MixPlan)
def episode_mix_plan(episode_id: str, request: Request) -> MixPlan:
    """Return the deterministic server-owned arrangement for the ready prefix."""
    actor = principal(request)
    owned(episode_id, actor)
    try:
        return canonical_mix_plan_for_episode(episode_id, actor)
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Mix plan is not ready") from error


@app.post(
    "/api/episodes/{episode_id}/prepare-mixdown",
    response_model=MixdownPreparationResult,
)
async def prepare_mixdown(episode_id: str, request: Request) -> MixdownPreparationResult:
    """Snapshot provider-backed music into owned assets without rendering."""
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    await to_thread.run_sync(_reject_published_copy, episode_id)
    try:
        return await _prepare_owned_music_assets(episode_id)
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error


@app.post(
    "/api/episodes/{episode_id}/program-render",
    response_model=ProgramRenderManifest,
)
async def render_program_stream(
    episode_id: str,
    request: Request,
) -> ProgramRenderManifest:
    """Append the current safe canonical prefix to the immutable programme feed."""

    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    episode = await to_thread.run_sync(orchestrator.get, episode_id)
    if episode.published_programme_id is not None:
        # A copy plays the published feed as it is; there is nothing of its own to render.
        return await _published_manifest(episode)
    return await _render_programme(episode_id)


_render_locks: dict[str, asyncio.Lock] = {}


async def _published_manifest(episode: LiveEpisode) -> ProgramRenderManifest:
    """The fixed, complete feed behind a listener's copy of a published programme."""
    source_id = await to_thread.run_sync(_published_manifest_source, episode)
    try:
        manifest = await load_program_manifest(audio_storage, source_id)
    except ProgramImmutabilityError as error:
        raise HTTPException(status_code=500, detail="Program render manifest is invalid") from error
    if manifest is None or not manifest.complete:
        raise HTTPException(status_code=404, detail="Program stream is not available")
    return manifest


async def _render_programme(episode_id: str, ahead_step: float | None = None) -> ProgramRenderManifest:
    """One render at a time per programme: they extend one append-only feed."""

    lock = _render_locks.setdefault(episode_id, asyncio.Lock())
    async with lock:
        return await _render_programme_locked(episode_id, ahead_step)


def _render_ahead_seconds(
    current: LiveEpisode, manifest: ProgramRenderManifest | None, step: float | None = None,
) -> float | None:
    """How far a finished programme is rendered up to now (None: render everything that is ready)."""

    if current.state not in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
        return None
    if step is not None and math.isinf(step):
        return None  # everything that is ready, in one pass
    reached = manifest.rendered_frontier_seconds if manifest is not None else 0.0
    return max(reached, current.program_playback_position_seconds) + (
        PROGRAMME_RENDER_AHEAD_SECONDS if step is None else step
    )


async def _render_programme_locked(episode_id: str, ahead_step: float | None = None) -> ProgramRenderManifest:
    started_at = monotonic()
    await to_thread.run_sync(_gc_program_render_cache, episode_id)
    try:
        manifest = await load_program_manifest(audio_storage, episode_id)
        before = await to_thread.run_sync(orchestrator.get, episode_id)
        ahead = _render_ahead_seconds(before, manifest, ahead_step)
        # Only the songs of the part about to be rendered are fetched, not the whole programme's.
        wanted, _ = _ready_prefix(before, None if ahead is None else ahead + _PROGRAMME_FETCH_EXTRA_SECONDS)
        fetch_started = monotonic()
        preparation = await _prepare_owned_music_assets(
            episode_id,
            ready_only=True,
            only_segment_ids={segment.id for segment in wanted},
        )
        fetch_seconds = monotonic() - fetch_started
        if not preparation.ready:
            raise HTTPException(
                status_code=409,
                detail="Program render music source is unavailable",
            )
        if manifest is not None:
            skipped_pending = await to_thread.run_sync(
                _skip_blocking_optional_narration_for_continuity,
                episode_id,
                manifest,
            )
            if skipped_pending:
                logger.info(
                    "program_render_narration_degraded episode_id=%s "
                    "reason=continuity_deadline skipped_count=%s",
                    episode_id,
                    len(skipped_pending),
                )

        current = await to_thread.run_sync(orchestrator.get, episode_id)
        plan = _canonical_render_plan(current, ahead)
        _, more_to_come = _ready_prefix(current, ahead)
        complete = (
            current.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}
            or _progressive_programme_ready_to_close(current)
        ) and not more_to_come
        try:
            rendered = await render_program_prefix(
                plan,
                audio_storage,
                complete=complete,
            )
        except ProgramImmutabilityError:
            if manifest is None or manifest.complete or current.state is EpisodeState.PUBLISHED:
                raise
            skipped_late = await to_thread.run_sync(
                _recover_late_optional_narration_for_frozen_prefix,
                episode_id,
                manifest,
            )
            if not skipped_late:
                raise
            logger.warning(
                "program_render_narration_degraded episode_id=%s "
                "reason=frozen_prefix_conflict skipped=%s frozen_frontier_s=%.1f "
                "playhead_s=%.1f",
                episode_id,
                ",".join(skipped_late),
                manifest.rendered_frontier_seconds,
                current.program_playback_position_seconds,
            )
            current = await to_thread.run_sync(orchestrator.get, episode_id)
            plan = await to_thread.run_sync(
                canonical_render_plan_for_episode,
                episode_id,
            )
            complete = (
                current.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}
                or _progressive_programme_ready_to_close(current)
            )
            rendered = await render_program_prefix(
                plan,
                audio_storage,
                complete=complete,
            )
        # Where the time goes: fetching the songs, or encoding.
        logger.info(
            "program_render_timing episode_id=%s audio_s=%.0f fetch_s=%.1f total_s=%.1f complete=%s",
            episode_id, rendered.rendered_frontier_seconds, fetch_seconds,
            monotonic() - started_at, rendered.complete,
        )
        if rendered.complete:
            await to_thread.run_sync(
                _finish_rendered_progressive_programme,
                episode_id,
                mix_plan_fingerprint(plan),
            )
        await to_thread.run_sync(
            _record_program_publication,
            episode_id,
            rendered.rendered_frontier_seconds,
            monotonic() - started_at,
        )
        return rendered
    except HTTPException:
        raise
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Program render plan is not ready") from error
    except ProgramImmutabilityError as error:
        logger.error(
            "program_render_immutability_violation episode_id=%s error=%s",
            episode_id,
            str(error),
        )
        raise HTTPException(
            status_code=409,
            detail="Program render prefix is immutable",
        ) from error
    except MixRendererUnavailableError as error:
        raise HTTPException(status_code=503, detail="Program renderer is unavailable") from error
    except MixSourceUnavailableError as error:
        raise HTTPException(status_code=409, detail="Program render source is unavailable") from error
    except MixRenderError as error:
        logger.warning(
            "program_render_failed episode_id=%s error=%s",
            episode_id,
            str(error),
        )
        raise HTTPException(status_code=502, detail="Program renderer failed") from error
    except OSError as error:
        logger.error(
            "program_render_storage_failed episode_id=%s errno=%s error=%s free_bytes=%s",
            episode_id,
            getattr(error, "errno", None),
            str(error),
            _program_render_free_bytes(),
        )
        raise HTTPException(status_code=500, detail="Program render storage failed") from error


@app.get(
    "/api/episodes/{episode_id}/program-render",
    response_model=ProgramRenderManifest,
)
async def program_render_status(
    episode_id: str,
    request: Request,
) -> ProgramRenderManifest:
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    episode = await to_thread.run_sync(orchestrator.get, episode_id)
    if episode.published_programme_id is not None:
        return await _published_manifest(episode)
    try:
        manifest = await load_program_manifest(audio_storage, episode_id)
    except ProgramImmutabilityError as error:
        raise HTTPException(status_code=500, detail="Program render manifest is invalid") from error
    if manifest is None:
        raise HTTPException(status_code=404, detail="Program render has not started")
    return manifest


@app.get("/api/program-streams/{episode_id}.m3u8")
async def program_stream_playlist(episode_id: str) -> Response:
    """Serve the mutable EVENT playlist; referenced transport chunks are immutable."""

    taken_down = await to_thread.run_sync(publication_repository.get_for_episode, episode_id)
    if taken_down is not None and taken_down.id in TAKEN_DOWN_PROGRAMMES:
        raise HTTPException(status_code=404, detail="Program stream is not ready")
    try:
        manifest = await load_program_manifest(audio_storage, episode_id)
    except ProgramImmutabilityError as error:
        raise HTTPException(status_code=500, detail="Program render manifest is invalid") from error
    if manifest is None or not manifest.chunks:
        raise HTTPException(status_code=404, detail="Program stream is not ready")
    return Response(
        content=hls_playlist(manifest),
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/api/episodes/{episode_id}/mixdown", response_model=MixdownArtifact)
async def episode_mixdown(episode_id: str, request: Request) -> MixdownArtifact:
    """Render the current canonical plan from already-owned local audio assets."""
    actor = principal(request)
    # The repository facade is synchronous (asyncio.run() under Postgres), so it must not run
    # on the request loop. Ownership first: an unknown or foreign id is a 404, never a 409 or a crash.
    await to_thread.run_sync(owned, episode_id, actor)
    await to_thread.run_sync(_reject_published_copy, episode_id)
    try:
        plan = await to_thread.run_sync(canonical_mix_plan_for_episode, episode_id, actor)
        with TemporaryDirectory(prefix="wavecast-mixdown-") as temporary:
            sources = await resolve_mix_sources(plan, audio_storage, Path(temporary) / "inputs")
            output_path = Path(temporary) / "mixdown.mp3"
            result = await to_thread.run_sync(
                lambda: render_mix(plan, sources, output_path)
            )
            content = output_path.read_bytes()
            fingerprint = mix_plan_fingerprint(plan)
            safe_episode_id = re.sub(r"[^a-zA-Z0-9_-]", "_", episode_id)
            key = f"mixdowns/{safe_episode_id}/{fingerprint}.mp3"
            audio_url = await audio_storage.put(
                key,
                content,
                "audio/mpeg",
                {"episode_id": episode_id, "plan_fingerprint": fingerprint},
            )
            return MixdownArtifact(
                episode_id=episode_id,
                plan_fingerprint=fingerprint,
                audio_url=audio_url,
                duration_seconds=result.duration_seconds,
            )
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Mix plan is not ready") from error
    except MixRendererUnavailableError as error:
        raise HTTPException(status_code=503, detail="Mix renderer is unavailable") from error
    except MixSourceUnavailableError as error:
        raise HTTPException(status_code=409, detail="Mix source is unavailable") from error
    except MixRenderError as error:
        raise HTTPException(status_code=502, detail="Mix renderer failed") from error
    except OSError as error:
        raise HTTPException(status_code=500, detail="Mixdown storage failed") from error


@app.post("/api/episodes/{episode_id}/ensure-buffer", response_model=LiveEpisode)
async def ensure_buffer(episode_id: str, request: Request, body: BufferRequest) -> LiveEpisode:
    del body
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    episode = await to_thread.run_sync(orchestrator.get, episode_id)
    return await to_thread.run_sync(
        lambda: _queue_progressive_generation(
            episode,
            force=True,
            retry_failed=True,
        )
    )


@app.post("/api/episodes/{episode_id}/advance", response_model=LiveEpisode)
async def advance_compatibility(episode_id: str, request: Request) -> LiveEpisode:
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    episode = await to_thread.run_sync(orchestrator.get, episode_id)
    return await to_thread.run_sync(
        lambda: _queue_progressive_generation(
            episode,
            force=True,
            retry_failed=True,
        )
    )


@app.post("/api/episodes/{episode_id}/heartbeat", response_model=LiveEpisode)
def heartbeat(episode_id: str, request: Request) -> LiveEpisode:
    episode = operate(
        episode_id,
        principal(request),
        lambda: orchestrator.heartbeat(episode_id),
    )
    return _queue_progressive_generation(episode)


@app.post("/api/episodes/{episode_id}/commit/{segment_id}", response_model=LiveEpisode)
def commit_segment(episode_id: str, segment_id: str, request: Request) -> LiveEpisode:
    return operate(
        episode_id,
        principal(request),
        lambda: orchestrator.commit_segment(episode_id, segment_id),
    )


@app.post(
    "/api/episodes/{episode_id}/complete-handoff/{completed_segment_id}/{successor_segment_id}",
    response_model=LiveEpisode,
)
def complete_handoff(
    episode_id: str,
    completed_segment_id: str,
    successor_segment_id: str,
    request: Request,
) -> LiveEpisode:
    episode = operate(
        episode_id,
        principal(request),
        lambda: orchestrator.complete_handoff(
            episode_id,
            completed_segment_id,
            successor_segment_id,
        ),
    )
    return _queue_progressive_generation(episode)


@app.post(
    "/api/episodes/{episode_id}/completed/{segment_id}",
    response_model=LiveEpisode,
)
def completed_segment(
    episode_id: str,
    segment_id: str,
    request: Request,
) -> LiveEpisode:
    episode = operate(
        episode_id,
        principal(request),
        lambda: orchestrator.complete_current_segment(
            episode_id,
            expected_segment_id=segment_id,
        ),
    )
    return _queue_progressive_generation(episode, force=True)


@app.post("/api/episodes/{episode_id}/completed", response_model=LiveEpisode)
def completed(episode_id: str, request: Request) -> LiveEpisode:
    episode = operate(
        episode_id, principal(request), lambda: orchestrator.complete_current_segment(episode_id)
    )
    return _queue_progressive_generation(episode, force=True)


@app.post("/api/episodes/{episode_id}/seek", response_model=LiveEpisode)
def seek(episode_id: str, request: Request, body: SeekRequest) -> LiveEpisode:
    episode = operate(
        episode_id, principal(request), lambda: orchestrator.seek(episode_id, body.position_seconds)
    )
    return _queue_progressive_generation(episode)


@app.post("/api/episodes/{episode_id}/playback-checkpoint", response_model=LiveEpisode)
def playback_checkpoint(
    episode_id: str, request: Request, body: PlaybackCheckpointRequest
) -> LiveEpisode:
    episode = operate(
        episode_id,
        principal(request),
        lambda: orchestrator.checkpoint_playback(episode_id, body.position_seconds),
    )
    return _queue_progressive_generation(episode)


@app.post(
    "/api/episodes/{episode_id}/program-playback-checkpoint",
    response_model=LiveEpisode,
)
def program_playback_checkpoint(
    episode_id: str,
    request: Request,
    body: ProgramPlaybackCheckpointRequest,
) -> LiveEpisode:
    episode = operate(
        episode_id,
        principal(request),
        lambda: orchestrator.checkpoint_program_playback(
            episode_id,
            body.position_seconds,
        ),
    )
    return _queue_progressive_generation(episode)


@app.post(
    "/api/episodes/{episode_id}/arm-handoff/{segment_id}",
    response_model=LiveEpisode,
)
def arm_handoff(episode_id: str, segment_id: str, request: Request) -> LiveEpisode:
    return operate(
        episode_id,
        principal(request),
        lambda: orchestrator.arm_handoff(episode_id, segment_id),
    )


@app.post("/api/episodes/{episode_id}/next", response_model=LiveEpisode)
def next_playable(episode_id: str, request: Request) -> LiveEpisode:
    episode = operate(
        episode_id, principal(request), lambda: orchestrator.next_playable(episode_id)
    )
    return _queue_progressive_generation(episode, force=True)


@app.post("/api/episodes/{episode_id}/leave", response_model=LiveEpisode)
def leave(episode_id: str, request: Request) -> LiveEpisode:
    episode = operate(
        episode_id, principal(request), lambda: orchestrator.leave(episode_id)
    )
    _cancel_generation(episode_id)
    return episode


@app.post("/api/episodes/{episode_id}/pause", response_model=LiveEpisode)
def pause(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, principal(request), lambda: orchestrator.pause(episode_id))


@app.post("/api/episodes/{episode_id}/resume", response_model=LiveEpisode)
def resume(episode_id: str, request: Request) -> LiveEpisode:
    episode = operate(
        episode_id, principal(request), lambda: orchestrator.resume(episode_id)
    )
    return _queue_progressive_generation(
        episode,
        force=True,
        retry_failed=True,
    )


@app.post(
    "/api/episodes/{episode_id}/segments/{segment_id}/materialize",
    response_model=LiveEpisode,
)
async def materialize_narration(
    episode_id: str, segment_id: str, request: Request
) -> LiveEpisode:
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    episode = await to_thread.run_sync(orchestrator.get, episode_id)
    try:
        segment = episode.segment(segment_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Segment not found") from error
    if not isinstance(segment, NarrationSegment):
        raise HTTPException(status_code=409, detail="Only narration segments can be materialized")
    try:
        with usage_scope(episode_id):
            await narration_materializer.materialize(segment)
        return await to_thread.run_sync(repository.save, episode)
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except ProviderConfigurationError as error:
        try:
            await to_thread.run_sync(repository.save, episode)
        except EpisodeConcurrencyError as save_error:
            raise HTTPException(
                status_code=409, detail="Episode changed; reload and retry"
            ) from save_error
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ProviderError as error:
        # Materializer leaves the segment SCRIPT_READY for a later retry.
        try:
            await to_thread.run_sync(repository.save, episode)
        except EpisodeConcurrencyError as save_error:
            raise HTTPException(
                status_code=409, detail="Episode changed; reload and retry"
            ) from save_error
        raise HTTPException(status_code=502, detail=str(error)) from error


def _owns_episode(episode: LiveEpisode, actor: AuthPrincipal) -> bool:
    return episode.listener_id == actor.listener_id or (
        actor.user_id is not None and episode.owner_user_id == actor.user_id
    )


def _full_versions_in_progress(actor: AuthPrincipal, *, excluding: str | None = None) -> int:
    """How many 完整版 of this listener are being prepared right now (a stalled one is not)."""
    now = datetime.now(UTC)
    count = 0
    for job in generation_job_repository.list_active(GenerationJobMode.FULL):
        if job.episode_id == excluding or is_stale(job, now):
            continue
        try:
            episode = orchestrator.get(job.episode_id)
        except EpisodeRuntimeError:
            continue
        if _owns_episode(episode, actor):
            count += 1
    return count


def _require_full_version_slot(actor: AuthPrincipal, *, excluding: str | None = None) -> None:
    busy = _full_versions_in_progress(actor, excluding=excluding) + _creating_requests(actor)
    if busy >= MAX_CONCURRENT_FULL_VERSIONS:
        raise HTTPException(
            status_code=429,
            detail=f"最多同时准备 {MAX_CONCURRENT_FULL_VERSIONS} 档",
        )


def _admit_full_version(episode_id: str, actor: AuthPrincipal) -> None:
    """Allow a 完整版 request: one already being prepared is left alone, a stalled one starts over."""
    episode = orchestrator.get(episode_id)
    if episode.state in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}:
        return
    job = generation_job_repository.get_for_episode(episode_id)
    if is_active(job):
        assert job is not None
        if not is_stale(job, datetime.now(UTC)):
            return
        generation_job_repository.cancel_for_episode(episode_id)
    _require_full_version_slot(actor, excluding=episode_id)


@app.post(
    "/api/episodes/{episode_id}/materialize",
    response_model=LiveEpisode,
    status_code=202,
)
async def materialize(episode_id: str, request: Request) -> LiveEpisode:
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    await to_thread.run_sync(_admit_full_version, episode_id, actor)
    return await _queue_full_generation(episode_id)


async def _queue_full_generation(episode_id: str) -> LiveEpisode:
    episode = await to_thread.run_sync(orchestrator.request_full_generation, episode_id)
    if episode.state is EpisodeState.MATERIALIZED:
        return episode
    try:
        await to_thread.run_sync(
            lambda: generation_job_repository.request(
                episode_id,
                GenerationJobMode.FULL,
            )
        )
    except Exception as error:
        await to_thread.run_sync(orchestrator.abort_full_generation, episode_id)
        raise HTTPException(
            status_code=503,
            detail="Full episode generation queue is unavailable",
        ) from error
    return episode


@dataclass
class _FullVersionRequest:
    """A 完整版 asked for from the tuner while its programme is still being made."""

    id: str
    listener_id: str
    user_id: str | None
    created_at: datetime
    status: str = "creating"
    episode_id: str | None = None
    programme_id: str | None = None
    title: str | None = None
    message: str | None = None


_full_version_requests: dict[str, _FullVersionRequest] = {}
_background_tasks: set[asyncio.Task[None]] = set()
_FULL_VERSION_REQUEST_KEEP_SECONDS = 60 * 60


def _owns_request(item: _FullVersionRequest, actor: AuthPrincipal) -> bool:
    return item.listener_id == actor.listener_id or (
        actor.user_id is not None and item.user_id == actor.user_id
    )


def _creating_requests(actor: AuthPrincipal) -> int:
    return sum(
        1
        for item in list(_full_version_requests.values())
        if item.status == "creating" and _owns_request(item, actor)
    )


async def _run_full_version_request(
    item: _FullVersionRequest, body: ProposalGenerationRequest, actor: AuthPrincipal,
) -> None:
    try:
        batch = await _make_proposals(body, actor)
        proposal = batch.proposals[0]
        started = await _start_episode(proposal.id, actor)
        # The slot was taken when the request was accepted, so it is not asked for again here.
        await _queue_full_generation(started.id)
        await to_thread.run_sync(orchestrator.leave, started.id)
        item.episode_id = started.id
        item.programme_id = started.seed_id
        item.title = started.title
        item.status = "ready"
    except HTTPException as error:
        item.status = "failed"
        item.message = error.detail if isinstance(error.detail, str) else None
    except Exception:  # noqa: BLE001 - the listener is told it did not work; the log has the rest
        logger.exception("full_version_request_failed request_id=%s", item.id)
        item.status = "failed"


@app.post("/api/full-versions", status_code=202)
async def prepare_full_version(
    body: ProposalGenerationRequest, request: Request,
) -> dict[str, str]:
    """Tune a programme and prepare its 完整版 without playing it.

    Answers at once: making the programme takes seconds, and the listener is free to leave. The
    work carries on here, and ``GET /api/full-versions/requests`` says how it went.
    """
    actor = principal(request)
    # Before anything is made, so a refusal costs the listener none of their allowance.
    await to_thread.run_sync(_require_full_version_slot, actor)
    now = datetime.now(UTC)
    for key, old in list(_full_version_requests.items()):
        if (now - old.created_at).total_seconds() > _FULL_VERSION_REQUEST_KEEP_SECONDS:
            _full_version_requests.pop(key, None)
    item = _FullVersionRequest(
        id=uuid4().hex, listener_id=actor.listener_id, user_id=actor.user_id, created_at=now,
    )
    _full_version_requests[item.id] = item
    task = asyncio.create_task(
        _run_full_version_request(item, body.model_copy(update={"count": 1}), actor)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"request_id": item.id}


class FullVersionRequestItem(BaseModel):
    request_id: str
    status: str
    episode_id: str | None = None
    programme_id: str | None = None
    title: str | None = None
    message: str | None = None


@app.get("/api/full-versions/requests", response_model=list[FullVersionRequestItem])
async def full_version_requests(ids: str, request: Request) -> list[FullVersionRequestItem]:
    """How each listed 完整版 request went: still being made, ready (with its episode), or failed."""
    actor = principal(request)
    wanted = [value for value in dict.fromkeys(ids.split(",")) if value][:10]
    return [
        FullVersionRequestItem(
            request_id=item.id, status=item.status, episode_id=item.episode_id,
            programme_id=item.programme_id, title=item.title, message=item.message,
        )
        for value in wanted
        if (item := _full_version_requests.get(value)) is not None and _owns_request(item, actor)
    ]


class FullVersionItem(BaseModel):
    episode_id: str
    programme_id: str
    status: FullVersionStatus
    progress: int


@app.get("/api/full-versions", response_model=list[FullVersionItem])
async def full_version_statuses(episode_ids: str, request: Request) -> list[FullVersionItem]:
    """Where the 完整版 of each listed episode stands (episodes that are not the caller's are left out)."""
    actor = principal(request)
    wanted = [item for item in dict.fromkeys(episode_ids.split(",")) if item][:30]

    def collect() -> list[FullVersionItem]:
        now = datetime.now(UTC)
        items: list[FullVersionItem] = []
        for episode_id in wanted:
            try:
                episode = orchestrator.get(episode_id)
            except EpisodeRuntimeError:
                continue
            if not _owns_episode(episode, actor):
                continue
            status = full_version_status(
                episode, generation_job_repository.get_for_episode(episode_id), now,
            )
            items.append(FullVersionItem(
                episode_id=episode_id,
                programme_id=episode.seed_id,
                status=status,
                progress=full_version_progress(episode, status),
            ))
        return items

    return await to_thread.run_sync(collect)


# --- Published programmes ---------------------------------------------------------------------------
# A finished programme shared as itself: mixed once, checked, and played by every listener's own copy
# from that one fixed feed (see docs/adr/0037-published-programmes.md).


def _published_budget() -> int:
    try:
        total = shutil.disk_usage(Path(AUDIO_ROOT)).total
    except OSError:
        total = 0
    return published_budget_bytes(total, PUBLISHED_AUDIO_BUDGET_BYTES)


def _publication_snapshot(episode: LiveEpisode) -> ProgrammeSnapshot | None:
    stored = proposal_repository.get(episode.seed_id)
    seed = None if stored is not None else _static_seed(episode.seed_id)
    proposal = stored or (ProgramProposal.from_episode_seed(seed) if seed is not None else None)
    if proposal is None:
        return None
    return ProgrammeSnapshot(
        title=proposal.title,
        cover_title=proposal.cover_title,
        description=proposal.short_description,
        estimated_duration_seconds=max(
            episode.timeline_duration_seconds, episode.program_estimated_duration_seconds,
        ),
        station=proposal.station,
        # Built-in programmes carry a generic outline that says nothing.
        route=list(proposal.editorial_route) if stored is not None else [],
        tags=list(dict.fromkeys([*proposal.genre_tags, *proposal.mood_tags]))[:6],
        opening_track_title=proposal.opening_track_title,
        opening_track_artist=proposal.opening_track_artist,
        cover=proposal.cover,
    )


def _mark_episode_published(episode_id: str) -> None:
    """The episode that was published is frozen: its audio is what listeners' copies play."""
    for _ in range(5):
        episode = repository.get(episode_id).model_copy(deep=True)
        if episode.state is EpisodeState.PUBLISHED:
            return
        episode.state = EpisodeState.PUBLISHED
        episode.last_activity_at = datetime.now(UTC)
        try:
            repository.save(episode)
            return
        except EpisodeConcurrencyError:
            continue


def _publication_plan_info(episode_id: str) -> tuple[float, str]:
    plan = _canonical_render_plan(orchestrator.get(episode_id))
    return plan.duration_seconds, mix_plan_fingerprint(plan)


public_shelf = PublicShelf(
    publication_repository,
    taken_down=lambda publication_id: publication_id in TAKEN_DOWN_PROGRAMMES,
)


publication_service = PublicationService(
    repository=publication_repository,
    episode=lambda episode_id: orchestrator.get(episode_id),
    mark_published=lambda episode_id: _mark_episode_published(episode_id),
    render=lambda episode_id, step: _render_programme(episode_id, step),
    plan_info=lambda episode_id: _publication_plan_info(episode_id),
    full_state=lambda episode: full_version_status(
        episode, generation_job_repository.get_for_episode(episode.id), datetime.now(UTC),
    ),
    storage=audio_storage,
    free_bytes=lambda: _program_render_free_bytes(),
    budget_bytes=lambda: _published_budget(),
    snapshot_for=lambda episode: _publication_snapshot(episode),
    taken_down=lambda publication_id: publication_id in TAKEN_DOWN_PROGRAMMES,
    on_change=lambda: public_shelf.invalidate(),
)


def _advance_publication_for(episode_id: str) -> None:
    publication = publication_repository.get_for_episode(episode_id)
    if publication is not None:
        publication_service.advance(publication.id)


def _owns_publication(publication: Publication, actor: AuthPrincipal) -> bool:
    return publication.owner_listener_id == actor.listener_id or (
        actor.user_id is not None and publication.owner_user_id == actor.user_id
    )


class PublishRequest(BaseModel):
    visibility: Literal["link", "public"] = "link"


class PublicationItem(BaseModel):
    """Where the publication of one of the caller's episodes stands."""

    id: str
    code: str
    episode_id: str
    status: str
    visibility: str
    #: The step being worked on: making the 完整版, mixing it, or nothing more to do.
    step: str
    progress: int
    error_code: str | None = None


def _publication_item(publication: Publication, episode: LiveEpisode) -> PublicationItem:
    status = publication.status
    if status is PublicationStatus.PREPARING:
        step = "full"
        progress = full_version_progress(
            episode,
            full_version_status(
                episode, generation_job_repository.get_for_episode(episode.id), datetime.now(UTC),
            ),
        )
    elif status is PublicationStatus.MIXING:
        # One pass: how far it has got is not known, and a made-up number would only mislead.
        step = "mix"
        progress = 0
    else:
        step = "done"
        progress = 100 if status in {PublicationStatus.PUBLISHED, PublicationStatus.REVOKED} else 0
    return PublicationItem(
        id=publication.id, code=publication.code, episode_id=publication.source_episode_id,
        status=status.value.lower(), visibility=publication.visibility.value.lower(),
        step=step, progress=progress, error_code=publication.error_code,
    )


def _refusal(error: PublishRefusal) -> HTTPException:
    status = {"limit": 429, "busy": 503, "space": 503}.get(error.code, 409)
    return HTTPException(
        status_code=status, detail=error.message, headers={"X-Wavecast-Refusal": error.code},
    )


@app.post("/api/episodes/{episode_id}/publish", response_model=PublicationItem, status_code=202)
async def publish_episode(episode_id: str, body: PublishRequest, request: Request) -> PublicationItem:
    """Share an episode of the caller's own as the programme itself.

    A programme that is not whole yet has its 完整版 made first; the mix and the checks follow, and
    the link opens once they are done. Answers at once, the rest is the server's work.
    """
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    return await _publish(episode_id, body, actor)


def _own_episode_of_programme(program_id: str, actor: AuthPrincipal) -> LiveEpisode | None:
    found = (
        repository.find_by_user_seed(actor.user_id, program_id) if actor.user_id is not None else None
    )
    return found or repository.find_by_listener_seed(actor.listener_id, program_id)


@app.post("/api/programs/{program_id}/publish", response_model=PublicationItem, status_code=202)
async def publish_programme(program_id: str, body: PublishRequest, request: Request) -> PublicationItem:
    """The same, from a programme: its episode is started first when the caller has none yet."""
    actor = principal(request)
    existing = await to_thread.run_sync(_own_episode_of_programme, program_id, actor)
    if existing is not None:
        return await _publish(existing.id, body, actor)
    proposal = await to_thread.run_sync(_proposal_for_program, program_id, actor)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Program not found")
    started = await _start_episode(program_id, actor)
    try:
        return await _publish(started.id, body, actor)
    finally:
        # Nobody is listening yet: the 完整版 is made while the listener is elsewhere.
        await to_thread.run_sync(orchestrator.leave, started.id)


@app.get("/api/programs/{program_id}/publication", response_model=PublicationItem)
async def programme_publication(program_id: str, request: Request) -> PublicationItem:
    """Where the publication of the caller's own programme stands (404: it has none)."""
    actor = principal(request)
    publication_service.bind_loop(asyncio.get_running_loop())

    def look() -> PublicationItem:
        episode = _own_episode_of_programme(program_id, actor)
        publication = (
            publication_repository.get_for_episode(episode.id) if episode is not None else None
        )
        if episode is None or publication is None or not _owns_publication(publication, actor):
            raise HTTPException(status_code=404, detail="Publication not found")
        publication = publication_service.advance(publication.id) or publication
        return _publication_item(publication, orchestrator.get(episode.id))

    return await to_thread.run_sync(look)


async def _publish(episode_id: str, body: PublishRequest, actor: AuthPrincipal) -> PublicationItem:
    episode = await to_thread.run_sync(orchestrator.get, episode_id)
    if episode.published_programme_id is not None:
        raise HTTPException(status_code=409, detail="Only your own programme can be shared")
    publication_service.bind_loop(asyncio.get_running_loop())
    existing = await to_thread.run_sync(publication_repository.get_for_episode, episode_id)
    needs_full = episode.state not in {EpisodeState.MATERIALIZED, EpisodeState.PUBLISHED}
    try:
        if needs_full and (existing is None or existing.status in {
            PublicationStatus.FAILED, PublicationStatus.PREPARING,
        }):
            await to_thread.run_sync(_admit_full_version, episode_id, actor)
            await _queue_full_generation(episode_id)
        publication = await to_thread.run_sync(
            lambda: publication_service.publish(
                episode_id,
                owner_listener_id=episode.listener_id,
                owner_user_id=episode.owner_user_id,
                visibility=Visibility(body.visibility.upper()),
            )
        )
    except PublishRefusal as error:
        raise _refusal(error) from error
    return await to_thread.run_sync(lambda: _publication_item(publication, orchestrator.get(episode_id)))


@app.get("/api/publications", response_model=list[PublicationItem])
async def publication_statuses(episode_ids: str, request: Request) -> list[PublicationItem]:
    """The publication of each listed episode (the caller's own; the rest are left out)."""
    actor = principal(request)
    publication_service.bind_loop(asyncio.get_running_loop())
    wanted = [item for item in dict.fromkeys(episode_ids.split(",")) if item][:30]

    def collect() -> list[PublicationItem]:
        items: list[PublicationItem] = []
        for episode_id in wanted:
            publication = publication_repository.get_for_episode(episode_id)
            if publication is None or not _owns_publication(publication, actor):
                continue
            publication = publication_service.advance(publication.id) or publication
            try:
                episode = orchestrator.get(episode_id)
            except EpisodeRuntimeError:
                continue
            items.append(_publication_item(publication, episode))
        return items

    return await to_thread.run_sync(collect)


def _owned_publication(publication_id: str, actor: AuthPrincipal) -> Publication:
    publication = publication_repository.get(publication_id)
    if publication is None or not _owns_publication(publication, actor):
        raise HTTPException(status_code=404, detail="Publication not found")
    return publication


class VisibilityRequest(BaseModel):
    visibility: Literal["link", "public"]


def _item_for(publication: Publication) -> PublicationItem:
    return _publication_item(publication, orchestrator.get(publication.source_episode_id))


@app.post("/api/publications/{publication_id}/revoke", response_model=PublicationItem)
async def revoke_publication(publication_id: str, request: Request) -> PublicationItem:
    """Stop sharing: no new copies and no listing. Copies that exist keep playing."""
    actor = principal(request)

    def revoke() -> PublicationItem:
        current = _owned_publication(publication_id, actor)
        return _item_for(publication_service.revoke(current.id) or current)

    return await to_thread.run_sync(revoke)


@app.post("/api/publications/{publication_id}/restore", response_model=PublicationItem)
async def restore_publication(publication_id: str, request: Request) -> PublicationItem:
    """Undo a revoke."""
    actor = principal(request)

    def restore() -> PublicationItem:
        current = _owned_publication(publication_id, actor)
        return _item_for(
            publication_service.restore(current.id, current.owner_listener_id, current.owner_user_id)
            or current
        )

    return await to_thread.run_sync(restore)


@app.post("/api/publications/{publication_id}/visibility", response_model=PublicationItem)
async def set_publication_visibility(
    publication_id: str, body: VisibilityRequest, request: Request,
) -> PublicationItem:
    actor = principal(request)

    def change() -> PublicationItem:
        current = _owned_publication(publication_id, actor)
        return _item_for(publication_service.set_visibility(current.id, Visibility(body.visibility.upper())) or current)

    return await to_thread.run_sync(change)


def _published_copy_of(publication: Publication, actor: AuthPrincipal) -> LiveEpisode | None:
    """The caller's own copy of a published programme, when they hold one."""
    found = (
        repository.find_by_user_seed(actor.user_id, publication.id)
        if actor.user_id is not None else None
    )
    return found or repository.find_by_listener_seed(actor.listener_id, publication.id)


@app.post("/api/published/{publication_id}/copy", response_model=LiveEpisode)
async def copy_published_programme(publication_id: str, request: Request) -> LiveEpisode:
    """The caller's own copy of a published programme: nothing is generated and no allowance is spent.

    Revoked programmes can only be reopened by people who already hold a copy.
    """
    actor = principal(request)

    def make() -> LiveEpisode:
        publication = publication_repository.get(publication_id)
        if publication is None or publication.id in TAKEN_DOWN_PROGRAMMES:
            raise HTTPException(status_code=404, detail="Program not found")
        held = _published_copy_of(publication, actor)
        if publication.status is PublicationStatus.REVOKED and held is None:
            raise HTTPException(status_code=410, detail="revoked")
        if publication.status not in {PublicationStatus.PUBLISHED, PublicationStatus.REVOKED}:
            raise HTTPException(status_code=404, detail="Program not found")
        try:
            return orchestrator.listen_to_published(
                orchestrator.get(publication.source_episode_id),
                programme_id=publication.id,
                title=publication.programme.title,
                listener_id=actor.listener_id,
                owner_user_id=actor.user_id,
            )
        except EpisodeConcurrencyError as error:
            raise HTTPException(status_code=409, detail="Episode creation raced; retry") from error
        except EpisodeRuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return await to_thread.run_sync(make)


@app.post("/api/published/{publication_id}/listen", status_code=204)
async def record_published_listen(publication_id: str, request: Request) -> Response:
    """A listener pressed play on a published programme: counted once per listener."""
    actor = principal(request)

    def record() -> None:
        publication = publication_repository.get(publication_id)
        if publication is None or publication.status is not PublicationStatus.PUBLISHED:
            return
        if _owns_publication(publication, actor):
            return  # an author's own listens do not make their programme more popular
        key = f"user:{actor.user_id}" if actor.user_id is not None else f"guest:{actor.listener_id}"
        publication_repository.record_listen(publication.id, key)

    await to_thread.run_sync(record)
    return Response(status_code=204)


class PublicShelfItem(BaseModel):
    """One card of 「大家都在听」: what the card shows, nothing about who made it or who listened."""

    id: str
    title: str
    cover_title: str | None = None
    station: StationId | None = None
    estimated_duration_seconds: int


class PublicShelfResponse(BaseModel):
    #: Empty on a first page: too few public programmes, the section is left out.
    items: list[PublicShelfItem]
    #: Asking again with these as `shown` could offer more.
    has_more: bool


@app.get("/api/public-shelf", response_model=PublicShelfResponse)
async def public_shelf_page(request: Request, shown: str = "") -> PublicShelfResponse:
    """The next programmes for 「大家都在听」: public ones, not the caller's own, not ones they hold.

    ``shown`` are the ids already offered (a 换一批 asks for others). Nothing is generated, so
    there is no daily limit; guests may ask too.
    """
    actor = principal(request)
    already = [item for item in dict.fromkeys(shown.split(",")) if item][:200]

    def build() -> PublicShelfResponse:
        page = public_shelf.page(
            is_mine=lambda publication: _owns_publication(publication, actor),
            holds_copy=lambda publication: _published_copy_of(publication, actor) is not None,
            shown=already,
        )
        if page.hidden:
            return PublicShelfResponse(items=[], has_more=False)
        return PublicShelfResponse(
            items=[
                PublicShelfItem(
                    id=item.id,
                    title=item.programme.title,
                    cover_title=item.programme.cover_title,
                    station=item.programme.station,
                    estimated_duration_seconds=item.programme.estimated_duration_seconds,
                )
                for item in page.items
            ],
            has_more=page.has_more,
        )

    return await to_thread.run_sync(build)


def _published_manifest_source(episode: LiveEpisode) -> str:
    """The episode whose programme feed an episode plays: the published one for a copy."""
    if episode.published_programme_id is None:
        return episode.id
    publication = publication_repository.get(episode.published_programme_id)
    if (
        publication is None
        or publication.id in TAKEN_DOWN_PROGRAMMES
        or publication.status not in {PublicationStatus.PUBLISHED, PublicationStatus.REVOKED}
    ):
        raise HTTPException(status_code=404, detail="Program stream is not available")
    return publication.source_episode_id


def _reject_published_copy(episode_id: str) -> None:
    if orchestrator.get(episode_id).published_programme_id is not None:
        raise HTTPException(status_code=409, detail="A shared programme cannot be re-mixed or exported")


@app.post("/api/episodes/{episode_id}/replan", response_model=LiveEpisode)
def replan(episode_id: str, request: Request, body: ReplaceRequest) -> LiveEpisode:
    return operate(
        episode_id,
        principal(request),
        lambda: orchestrator.replace_speculative_music(episode_id, body.title),
    )


@app.get("/api/episodes/{episode_id}/events")
async def episode_events(
    episode_id: str, request: Request, once: bool = False
) -> StreamingResponse:
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)

    async def stream() -> AsyncIterator[str]:
        version = -1
        while not await request.is_disconnected():
            current = await to_thread.run_sync(orchestrator.get, episode_id)
            if current.version != version:
                version = current.version
                payload = json.dumps(current.model_dump(mode="json"), ensure_ascii=False)
                yield f"id: {version}\nevent: episode_state_changed\ndata: {payload}\n\n"
                if once:
                    return
            await asyncio.sleep(0.25)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
