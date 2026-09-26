import asyncio
import json
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
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
from wavecast.deployment import audio_root_from_env, normalize_database_url
from wavecast.materialization import (
    MusicSnapshotError,
    MusicSnapshotStore,
    MusicSourceClassification,
    MusicSourceKind,
    NarrationMaterializer,
    ProviderPlaybackSnapshotFetcher,
    classify_music_source,
)
from wavecast.models.episode import (
    CoverParams,
    EpisodeSeed,
    EpisodeState,
    LiveEpisode,
    MusicSegment,
    NarrationSegment,
    PlayableEpisode,
)
from wavecast.orchestration import EpisodeOrchestrator, InlineGenerationScheduler
from wavecast.orchestration.episode import EpisodeRuntimeError, InMemoryEpisodeRepository
from wavecast.orchestration.runtime import StagedProgressiveRuntimeAdapter
from wavecast.proposals import (
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
from wavecast.providers.audius import AudiusMusicProvider
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import AudioProvider, AudioSource, ObjectStorageProvider
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.factory import build_music_registry
from wavecast.providers.fakes import MockAudioProvider, MockTTSProvider
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.providers.music_http import SidecarMusicProvider
from wavecast.providers.netease import NeteaseMusicProvider
from wavecast.providers.playback import ResolvedPlaybackRequest
from wavecast.providers.qqmusic import QQMusicProvider
from wavecast.providers.retrieval import MusicRetrievalService
from wavecast.providers.usage import UsageLedger
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
    render_mix,
    resolve_mix_sources,
)
from wavecast.rendering.fingerprint import mix_plan_fingerprint
from wavecast.storage import (
    EpisodeConcurrencyError,
    GenerationQuotaRepository,
    InMemoryGenerationQuotaRepository,
    InMemoryUserLibraryRepository,
    LocalObjectStorageProvider,
    PostgresEpisodeRepository,
    PostgresGenerationQuotaRepository,
    PostgresUserLibraryRepository,
    QuotaExceededError,
    UserLibraryRepository,
)
from wavecast.storage.episodes import EpisodeRepository
from wavecast.storage.recommendations import PostgresProgramIdeaRepository
from wavecast.storage.user_context import (
    PostgresUserEventRepository,
    PostgresUserPreferencesRepository,
)
from wavecast.user_context import (
    InMemoryUserEventRepository,
    InMemoryUserPreferencesRepository,
    UserEvent,
    UserEventInput,
    UserEventRepository,
    UserEventService,
    UserPreferences,
    UserPreferencesRepository,
    UserPreferencesUpdate,
)

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
if DATABASE_URL:
    from wavecast.storage import PostgresProgramProposalRepository

    proposal_repository = PostgresProgramProposalRepository(DATABASE_URL)
    user_library_repository = PostgresUserLibraryRepository(DATABASE_URL)
    generation_quota_repository = PostgresGenerationQuotaRepository(DATABASE_URL)

GUEST_PROGRAM_LIMIT = int(os.getenv("WAVECAST_GUEST_PROGRAM_LIMIT", "3"))
AUTH_DAILY_PROGRAM_LIMIT = int(os.getenv("WAVECAST_AUTH_DAILY_PROGRAM_LIMIT", "20"))
GLOBAL_DAILY_PROGRAM_LIMIT = int(os.getenv("WAVECAST_GLOBAL_DAILY_PROGRAM_LIMIT", "100"))
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


def _build_recommendation_planner(settings: ProviderSettings) -> RecommendationPlanner:
    mode = os.getenv("WAVECAST_RECOMMENDATION_PLANNER", "deterministic").strip().lower()
    if mode == "deterministic":
        return DeterministicRecommendationPlanner()
    if mode != "deepseek":
        raise ProviderConfigurationError(
            "WAVECAST_RECOMMENDATION_PLANNER must be deterministic or deepseek"
        )

    # Recommendation inference is an independently gated capability.  It may use
    # DeepSeek while episode assembly, TTS, and music providers remain in mock
    # mode, so enabling personalized ideas does not implicitly enable paid
    # generation elsewhere.
    recommendation_settings = settings.for_live_capability()
    recommendation_settings.credential_for("deepseek")
    ledger = UsageLedger()
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


def _build_proposal_generator(settings: ProviderSettings) -> ProgramProposalGenerator:
    if settings.resolved_proposal_planner == "mock":
        return DeterministicMockProgramProposalGenerator()
    live_settings = settings.for_live_capability()
    live_settings.credential_for("deepseek")
    ledger = UsageLedger()
    return LLMProgramProposalGenerator(
        DeepSeekLLMProvider(live_settings, ledger=ledger),
        MusicRetrievalService(build_music_registry(settings)),
    )


proposal_generator: ProgramProposalGenerator | None = _build_proposal_generator(
    _provider_settings
)
repository: EpisodeRepository = (
    PostgresEpisodeRepository(DATABASE_URL) if DATABASE_URL else InMemoryEpisodeRepository()
)


def _build_tts_provider(
    settings: ProviderSettings, storage: ObjectStorageProvider
) -> MiniMaxTTSProvider | MockTTSProvider:
    if settings.resolved_tts_provider == "mock":
        return MockTTSProvider(storage)
    live_settings = settings.for_live_capability()
    live_settings.credential_for("minimax")
    if not live_settings.minimax_tts_voice_id:
        raise ProviderConfigurationError("minimax TTS requires MINIMAX_TTS_VOICE_ID")
    return MiniMaxTTSProvider(live_settings, storage=storage)


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


_tts_provider = _build_tts_provider(_provider_settings, audio_storage)
narration_materializer = NarrationMaterializer(_tts_provider, audio_storage)


def _build_progressive_runtime(
    settings: ProviderSettings, storage: ObjectStorageProvider
) -> StagedProgressiveRuntimeAdapter | None:
    if settings.mode != "live" and not settings.has_live_progressive_intelligence:
        return None
    return StagedProgressiveRuntimeAdapter(
        create_episode_assembly_service(settings, storage=storage)
    )


progressive_runtime = _build_progressive_runtime(_provider_settings, audio_storage)
audio_provider = _build_audio_provider(_provider_settings)
orchestrator = EpisodeOrchestrator(
    repository,
    audio_provider=audio_provider,
    progressive_runtime=progressive_runtime,
)
scheduler = InlineGenerationScheduler(orchestrator)


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
    global repository, orchestrator, scheduler, progressive_runtime
    repository = episode_repository
    if progressive_runtime_adapter is not None:
        progressive_runtime = progressive_runtime_adapter
    orchestrator = EpisodeOrchestrator(
        repository,
        audio_provider=audio_provider,
        progressive_runtime=progressive_runtime,
    )
    scheduler = InlineGenerationScheduler(orchestrator)


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
        scheduler
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

app = FastAPI(title="Wavecast API", version="0.2.0")
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
    preferences = UserPreferences(
        user_id=authenticated_user(request),
        **body.model_dump(),
    )
    return user_preferences_repository.save(preferences)


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


@app.get("/api/recommendations/me", response_model=list[ProgramIdeaResponse])
def list_recommendations(request: Request) -> list[ProgramIdeaResponse]:
    ideas = _recommendation_service().inventory_for_user(authenticated_user(request))
    return [ProgramIdeaResponse.from_idea(idea) for idea in ideas]


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
        raise HTTPException(
            status_code=502,
            detail=f"Program proposal generation failed ({error.reason})",
        ) from error
    except ProviderError as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        await restore_available()
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


async def _resolve_sidecar_playback_request(
    provider_name: str, track_id: str
) -> ResolvedPlaybackRequest:
    provider = _build_sidecar_provider(provider_name)
    try:
        if hasattr(provider, "resolve_upstream_playback_request"):
            return await provider.resolve_upstream_playback_request(
                f"{provider_name}:{track_id}"
            )
        return ResolvedPlaybackRequest(
            provider=provider_name,
            url=await provider.resolve_upstream_playback_url(
                f"{provider_name}:{track_id}"
            ),
        )
    finally:
        await provider.aclose()


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


@app.post("/api/program-proposals", response_model=ProgramProposalBatch)
async def create_program_proposals(
    body: ProposalGenerationRequest, request: Request,
) -> ProgramProposalBatch:
    if proposal_generator is None:
        raise HTTPException(status_code=503, detail="Program proposal generation is not configured")
    owner = principal(request)
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
        raise HTTPException(status_code=502, detail=f"Program proposal generation failed ({error.reason})") from error
    except ProviderError as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        raise HTTPException(status_code=502, detail="Program proposal provider failed") from error
    except ProposalPersistenceConflict as error:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        raise HTTPException(status_code=409, detail="Program proposal could not be saved") from error
    except BaseException:
        await to_thread.run_sync(generation_quota_repository.release, reservations)
        raise


@app.post("/api/episodes/from-seed/{seed_id}", response_model=LiveEpisode)
def create_episode(seed_id: str, request: Request) -> LiveEpisode:
    actor = principal(request)
    seed = _static_seed(seed_id)
    if seed is None:
        proposal = _proposal_for_program(seed_id, actor)
        seed = proposal.to_episode_seed() if proposal is not None else None
    if seed is None:
        raise HTTPException(status_code=404, detail="Episode seed not found")
    try:
        return orchestrator.start_or_resume(seed, actor.listener_id, actor.user_id)
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


def canonical_mix_plan_for_episode(episode_id: str, actor: AuthPrincipal) -> MixPlan:
    """Build the canonical arrangement for the currently ready timeline prefix."""
    current = orchestrator.get(episode_id)
    ready_segments: list[MusicSegment | NarrationSegment] = []
    for segment in current.timeline_segments:
        if not segment.is_audio_ready:
            break
        ready_segments.append(cast(MusicSegment | NarrationSegment, segment))
    if not ready_segments:
        raise ValueError("mix plan is not ready")
    return plan_episode_mix(PlayableEpisode(id=current.id, segments=ready_segments))


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
    owned(episode_id, actor)
    current = orchestrator.get(episode_id)
    working = current.model_copy(deep=True)
    updates: list[tuple[MusicSegment, str, str, int]] = []
    blocked: list[BlockedMusicSource] = []
    owned_count = 0
    snapshotted_count = 0
    reused_count = 0

    for segment in working.timeline_segments:
        if not isinstance(segment, MusicSegment):
            continue
        classification = classify_music_source(segment.audio_source_url or "")
        if classification.kind is MusicSourceKind.OWNED_ASSET:
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
            (segment, snapshot.playback_url, snapshot.asset_ref, snapshot.duration_seconds)
        )
        owned_count += 1
        if snapshot.reused:
            reused_count += 1
        else:
            snapshotted_count += 1

    if blocked:
        return MixdownPreparationResult(
            episodeId=episode_id,
            ready=False,
            ownedMusicCount=owned_count,
            snapshottedMusicCount=snapshotted_count,
            reusedMusicCount=reused_count,
            blockedSources=blocked,
        )

    for segment, playback_url, asset_ref, duration_seconds in updates:
        segment.audio_source_url = playback_url
        segment.asset_ref = asset_ref
        segment.actual_duration_seconds = duration_seconds
    if updates:
        try:
            repository.save(working)
        except EpisodeConcurrencyError as error:
            raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error

    return MixdownPreparationResult(
        episodeId=episode_id,
        ready=True,
        ownedMusicCount=owned_count,
        snapshottedMusicCount=snapshotted_count,
        reusedMusicCount=reused_count,
        blockedSources=[],
    )


@app.post("/api/episodes/{episode_id}/mixdown", response_model=MixdownArtifact)
async def episode_mixdown(episode_id: str, request: Request) -> MixdownArtifact:
    """Render the current canonical plan from already-owned local audio assets."""
    actor = principal(request)
    owned(episode_id, actor)
    try:
        plan = canonical_mix_plan_for_episode(episode_id, actor)
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
    return await operate_async(
        episode_id,
        principal(request),
        lambda: scheduler.ensure_buffer(episode_id, target_chapters=body.target_chapters),
    )


@app.post("/api/episodes/{episode_id}/advance", response_model=LiveEpisode)
async def advance_compatibility(episode_id: str, request: Request) -> LiveEpisode:
    return await operate_async(
        episode_id, principal(request), lambda: scheduler.ensure_buffer(episode_id)
    )


@app.post("/api/episodes/{episode_id}/heartbeat", response_model=LiveEpisode)
def heartbeat(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, principal(request), lambda: orchestrator.heartbeat(episode_id))


@app.post("/api/episodes/{episode_id}/commit/{segment_id}", response_model=LiveEpisode)
def commit_segment(episode_id: str, segment_id: str, request: Request) -> LiveEpisode:
    return operate(
        episode_id,
        principal(request),
        lambda: orchestrator.commit_segment(episode_id, segment_id),
    )


@app.post("/api/episodes/{episode_id}/completed", response_model=LiveEpisode)
def completed(episode_id: str, request: Request) -> LiveEpisode:
    return operate(
        episode_id, principal(request), lambda: orchestrator.complete_current_segment(episode_id)
    )


@app.post("/api/episodes/{episode_id}/seek", response_model=LiveEpisode)
def seek(episode_id: str, request: Request, body: SeekRequest) -> LiveEpisode:
    return operate(
        episode_id, principal(request), lambda: orchestrator.seek(episode_id, body.position_seconds)
    )


@app.post("/api/episodes/{episode_id}/playback-checkpoint", response_model=LiveEpisode)
def playback_checkpoint(
    episode_id: str, request: Request, body: PlaybackCheckpointRequest
) -> LiveEpisode:
    return operate(
        episode_id,
        principal(request),
        lambda: orchestrator.checkpoint_playback(episode_id, body.position_seconds),
    )


@app.post("/api/episodes/{episode_id}/next", response_model=LiveEpisode)
def next_playable(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, principal(request), lambda: orchestrator.next_playable(episode_id))


@app.post("/api/episodes/{episode_id}/leave", response_model=LiveEpisode)
def leave(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, principal(request), lambda: orchestrator.leave(episode_id))


@app.post("/api/episodes/{episode_id}/pause", response_model=LiveEpisode)
def pause(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, principal(request), lambda: orchestrator.pause(episode_id))


@app.post("/api/episodes/{episode_id}/resume", response_model=LiveEpisode)
def resume(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, principal(request), lambda: orchestrator.resume(episode_id))


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


@app.post("/api/episodes/{episode_id}/materialize", response_model=LiveEpisode)
async def materialize(episode_id: str, request: Request) -> LiveEpisode:
    actor = principal(request)
    await to_thread.run_sync(owned, episode_id, actor)
    episode: LiveEpisode | None = None
    try:
        await scheduler.materialize_all(episode_id)
        episode = await to_thread.run_sync(orchestrator.prepare_materialization, episode_id)
        for segment in episode.timeline_segments:
            if isinstance(segment, NarrationSegment) and not segment.is_audio_ready:
                await narration_materializer.materialize(segment)
        episode.state = EpisodeState.MATERIALIZED
        episode.last_activity_at = orchestrator.now()
        return await to_thread.run_sync(repository.save, episode)
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except ProviderConfigurationError as error:
        if episode is not None:
            episode.state = EpisodeState.STREAMING
            try:
                await to_thread.run_sync(repository.save, episode)
            except EpisodeConcurrencyError as save_error:
                raise HTTPException(
                    status_code=409, detail="Episode changed; reload and retry"
                ) from save_error
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ProviderError as error:
        if episode is not None:
            episode.state = EpisodeState.STREAMING
            try:
                await to_thread.run_sync(repository.save, episode)
            except EpisodeConcurrencyError as save_error:
                raise HTTPException(
                    status_code=409, detail="Episode changed; reload and retry"
                ) from save_error
        raise HTTPException(status_code=502, detail=str(error)) from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
