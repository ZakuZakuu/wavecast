import asyncio
import json
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
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
from wavecast.providers.audius import AudiusMusicProvider
from wavecast.providers.config import ProviderSettings
from wavecast.providers.contracts import ObjectStorageProvider
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.fakes import MockTTSProvider
from wavecast.providers.minimax import MiniMaxTTSProvider
from wavecast.providers.music_http import SidecarMusicProvider
from wavecast.providers.netease import NeteaseMusicProvider
from wavecast.providers.playback import ResolvedPlaybackRequest
from wavecast.providers.qqmusic import QQMusicProvider
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
    LocalObjectStorageProvider,
    PostgresEpisodeRepository,
)
from wavecast.storage.episodes import EpisodeRepository

LISTENER_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
DATABASE_URL = os.getenv("WAVECAST_DATABASE_URL")
AUDIO_ROOT = os.getenv("WAVECAST_AUDIO_ROOT", ".wavecast-data/audio")
audio_storage: ObjectStorageProvider = LocalObjectStorageProvider(AUDIO_ROOT)
_provider_settings = ProviderSettings.from_env()
repository: EpisodeRepository = (
    PostgresEpisodeRepository(DATABASE_URL) if DATABASE_URL else InMemoryEpisodeRepository()
)


def _build_tts_provider(
    settings: ProviderSettings, storage: ObjectStorageProvider
) -> MiniMaxTTSProvider | MockTTSProvider:
    if settings.mode == "mock":
        return MockTTSProvider(storage)
    return MiniMaxTTSProvider(settings, storage=storage)


_tts_provider = _build_tts_provider(_provider_settings, audio_storage)
narration_materializer = NarrationMaterializer(_tts_provider, audio_storage)


def _build_progressive_runtime(
    settings: ProviderSettings, storage: ObjectStorageProvider
) -> StagedProgressiveRuntimeAdapter | None:
    try:
        return StagedProgressiveRuntimeAdapter(
            create_episode_assembly_service(settings, storage=storage)
        )
    except ProviderConfigurationError:
        if settings.mode == "live":
            raise
        return None


progressive_runtime = _build_progressive_runtime(_provider_settings, audio_storage)
orchestrator = EpisodeOrchestrator(repository, progressive_runtime=progressive_runtime)
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


def owned(episode_id: str, listener_id: str) -> None:
    try:
        orchestrator.get(episode_id, listener_id)
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=404, detail="Episode not found") from error


def operate(episode_id: str, listener_id: str, operation: Callable[[], LiveEpisode]) -> LiveEpisode:
    owned(episode_id, listener_id)
    try:
        return operation()
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


async def operate_async(
    episode_id: str,
    listener_id: str,
    operation: Callable[[], Awaitable[LiveEpisode]],
) -> LiveEpisode:
    await to_thread.run_sync(owned, episode_id, listener_id)
    try:
        return await operation()
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode changed; reload and retry") from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "postgres" if DATABASE_URL else "mock"}


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


@app.get("/api/seeds", response_model=list[EpisodeSeed])
def list_seeds() -> list[EpisodeSeed]:
    return SEEDS


@app.post("/api/episodes/from-seed/{seed_id}", response_model=LiveEpisode)
def create_episode(seed_id: str, request: Request) -> LiveEpisode:
    seed = next((candidate for candidate in SEEDS if candidate.id == seed_id), None)
    if seed is None:
        raise HTTPException(status_code=404, detail="Episode seed not found")
    try:
        return orchestrator.start_or_resume(seed, listener(request))
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
            listener_id=listener(request),
        )
    except EpisodeConcurrencyError as error:
        raise HTTPException(status_code=409, detail="Episode creation raced; retry") from error
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/episodes/{episode_id}", response_model=LiveEpisode)
def episode(episode_id: str, request: Request) -> LiveEpisode:
    owned(episode_id, listener(request))
    return orchestrator.get(episode_id)


def canonical_mix_plan_for_episode(episode_id: str, listener_id: str) -> MixPlan:
    """Build the canonical arrangement for the currently ready timeline prefix."""
    current = orchestrator.get(episode_id, listener_id)
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
    listener_id = listener(request)
    owned(episode_id, listener_id)
    try:
        return canonical_mix_plan_for_episode(episode_id, listener_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Mix plan is not ready") from error


@app.post(
    "/api/episodes/{episode_id}/prepare-mixdown",
    response_model=MixdownPreparationResult,
)
async def prepare_mixdown(episode_id: str, request: Request) -> MixdownPreparationResult:
    """Snapshot provider-backed music into owned assets without rendering."""
    listener_id = listener(request)
    owned(episode_id, listener_id)
    current = orchestrator.get(episode_id, listener_id)
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
    listener_id = listener(request)
    owned(episode_id, listener_id)
    try:
        plan = canonical_mix_plan_for_episode(episode_id, listener_id)
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
        listener(request),
        lambda: scheduler.ensure_buffer(episode_id, target_chapters=body.target_chapters),
    )


@app.post("/api/episodes/{episode_id}/advance", response_model=LiveEpisode)
async def advance_compatibility(episode_id: str, request: Request) -> LiveEpisode:
    return await operate_async(
        episode_id, listener(request), lambda: scheduler.ensure_buffer(episode_id)
    )


@app.post("/api/episodes/{episode_id}/heartbeat", response_model=LiveEpisode)
def heartbeat(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, listener(request), lambda: orchestrator.heartbeat(episode_id))


@app.post("/api/episodes/{episode_id}/completed", response_model=LiveEpisode)
def completed(episode_id: str, request: Request) -> LiveEpisode:
    return operate(
        episode_id, listener(request), lambda: orchestrator.complete_current_segment(episode_id)
    )


@app.post("/api/episodes/{episode_id}/seek", response_model=LiveEpisode)
def seek(episode_id: str, request: Request, body: SeekRequest) -> LiveEpisode:
    return operate(
        episode_id, listener(request), lambda: orchestrator.seek(episode_id, body.position_seconds)
    )


@app.post("/api/episodes/{episode_id}/playback-checkpoint", response_model=LiveEpisode)
def playback_checkpoint(
    episode_id: str, request: Request, body: PlaybackCheckpointRequest
) -> LiveEpisode:
    return operate(
        episode_id,
        listener(request),
        lambda: orchestrator.checkpoint_playback(episode_id, body.position_seconds),
    )


@app.post("/api/episodes/{episode_id}/next", response_model=LiveEpisode)
def next_playable(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, listener(request), lambda: orchestrator.next_playable(episode_id))


@app.post("/api/episodes/{episode_id}/leave", response_model=LiveEpisode)
def leave(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, listener(request), lambda: orchestrator.leave(episode_id))


@app.post("/api/episodes/{episode_id}/pause", response_model=LiveEpisode)
def pause(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, listener(request), lambda: orchestrator.pause(episode_id))


@app.post("/api/episodes/{episode_id}/resume", response_model=LiveEpisode)
def resume(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, listener(request), lambda: orchestrator.resume(episode_id))


@app.post(
    "/api/episodes/{episode_id}/segments/{segment_id}/materialize",
    response_model=LiveEpisode,
)
async def materialize_narration(
    episode_id: str, segment_id: str, request: Request
) -> LiveEpisode:
    listener_id = listener(request)
    await to_thread.run_sync(owned, episode_id, listener_id)
    episode = await to_thread.run_sync(orchestrator.get, episode_id, listener_id)
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
    listener_id = listener(request)
    await to_thread.run_sync(owned, episode_id, listener_id)
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
        listener(request),
        lambda: orchestrator.replace_speculative_music(episode_id, body.title),
    )


@app.get("/api/episodes/{episode_id}/events")
async def episode_events(
    episode_id: str, request: Request, once: bool = False
) -> StreamingResponse:
    listener_id = listener(request)
    await to_thread.run_sync(owned, episode_id, listener_id)

    async def stream() -> AsyncIterator[str]:
        version = -1
        while not await request.is_disconnected():
            current = await to_thread.run_sync(orchestrator.get, episode_id, listener_id)
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
