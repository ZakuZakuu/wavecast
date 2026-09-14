import asyncio
import json
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from wavecast.models.episode import CoverParams, EpisodeSeed, LiveEpisode
from wavecast.orchestration import EpisodeOrchestrator, InlineGenerationScheduler
from wavecast.orchestration.episode import EpisodeRuntimeError, InMemoryEpisodeRepository
from wavecast.storage import PostgresEpisodeRepository

LISTENER_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
DATABASE_URL = os.getenv("WAVECAST_DATABASE_URL")
repository = (
    PostgresEpisodeRepository(DATABASE_URL) if DATABASE_URL else InMemoryEpisodeRepository()
)
orchestrator = EpisodeOrchestrator(repository)
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


def listener(request: Request) -> str:
    return cast(str, request.state.listener_id)


def owned(episode_id: str, listener_id: str) -> None:
    try:
        orchestrator.get(episode_id, listener_id)
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=404, detail="Episode not found") from error


def operate(episode_id: str, listener_id: str, operation: Callable[[], LiveEpisode]) -> LiveEpisode:
    owned(episode_id, listener_id)
    try:
        return operation()
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "postgres" if DATABASE_URL else "mock"}


@app.get("/api/seeds", response_model=list[EpisodeSeed])
def list_seeds() -> list[EpisodeSeed]:
    return SEEDS


@app.post("/api/episodes/from-seed/{seed_id}", response_model=LiveEpisode)
def create_episode(seed_id: str, request: Request) -> LiveEpisode:
    seed = next((candidate for candidate in SEEDS if candidate.id == seed_id), None)
    if seed is None:
        raise HTTPException(status_code=404, detail="Episode seed not found")
    return orchestrator.start_or_resume(seed, listener(request))


@app.get("/api/episodes/{episode_id}", response_model=LiveEpisode)
def episode(episode_id: str, request: Request) -> LiveEpisode:
    owned(episode_id, listener(request))
    return orchestrator.get(episode_id)


@app.post("/api/episodes/{episode_id}/ensure-buffer", response_model=LiveEpisode)
def ensure_buffer(episode_id: str, request: Request, body: BufferRequest) -> LiveEpisode:
    return operate(
        episode_id,
        listener(request),
        lambda: scheduler.ensure_buffer(episode_id, target_chapters=body.target_chapters),
    )


@app.post("/api/episodes/{episode_id}/advance", response_model=LiveEpisode)
def advance_compatibility(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, listener(request), lambda: scheduler.ensure_buffer(episode_id))


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


@app.post("/api/episodes/{episode_id}/materialize", response_model=LiveEpisode)
def materialize(episode_id: str, request: Request) -> LiveEpisode:
    return operate(episode_id, listener(request), lambda: orchestrator.materialize_all(episode_id))


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
    owned(episode_id, listener_id)

    async def stream() -> AsyncIterator[str]:
        version = -1
        while not await request.is_disconnected():
            current = orchestrator.get(episode_id, listener_id)
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
