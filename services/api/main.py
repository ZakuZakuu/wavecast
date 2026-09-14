from collections.abc import Callable

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from wavecast.models.episode import CoverParams, EpisodeSeed, LiveEpisode
from wavecast.orchestration.episode import (
    EpisodeOrchestrator,
    EpisodeRuntimeError,
    InMemoryEpisodeRepository,
)

app = FastAPI(title="Wavecast API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    EpisodeSeed(
        id="boss-choir",
        title="游戏最终 Boss 为什么总爱用合唱？",
        topic="游戏配乐中的合唱与决战感",
        short_description="从空间、仪式感到压迫感，拆开最终战配乐的声音语言。",
        estimated_duration_seconds=26 * 60,
        opening_track_ref="mock:opening",
        opening_track_title="Neon First Light",
        opening_track_artist="Mira Fields",
        cover=CoverParams(family="archive", seed=987, palette=("#3d261b", "#ffc857")),
    ),
]

orchestrator = EpisodeOrchestrator(InMemoryEpisodeRepository())


class SeekRequest(BaseModel):
    position_seconds: int = Field(ge=0)


class ReplaceRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class TickRequest(BaseModel):
    elapsed_seconds: int = Field(ge=0, le=60)


class BufferRequest(BaseModel):
    target_chapters: int = Field(default=2, ge=1, le=2)


def get_episode_or_404(episode_id: str) -> LiveEpisode:
    try:
        return orchestrator.get(episode_id)
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=404, detail="Episode not found") from error


def operate(operation: Callable[[], LiveEpisode]) -> LiveEpisode:
    try:
        return operation()
    except EpisodeRuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "mock"}


@app.get("/api/seeds", response_model=list[EpisodeSeed])
def list_seeds() -> list[EpisodeSeed]:
    return SEEDS


@app.post("/api/episodes/from-seed/{seed_id}", response_model=LiveEpisode)
def create_episode(seed_id: str) -> LiveEpisode:
    seed = next((candidate for candidate in SEEDS if candidate.id == seed_id), None)
    if seed is None:
        raise HTTPException(status_code=404, detail="Episode seed not found")
    return orchestrator.start_or_resume(seed)


@app.get("/api/episodes/{episode_id}", response_model=LiveEpisode)
def episode(episode_id: str) -> LiveEpisode:
    return get_episode_or_404(episode_id)


@app.post("/api/episodes/{episode_id}/advance", response_model=LiveEpisode)
def advance(episode_id: str) -> LiveEpisode:
    return operate(lambda: orchestrator.ensure_buffer(episode_id))


@app.post("/api/episodes/{episode_id}/ensure-buffer", response_model=LiveEpisode)
def ensure_buffer(episode_id: str, request: BufferRequest) -> LiveEpisode:
    return operate(
        lambda: orchestrator.ensure_buffer(episode_id, target_chapters=request.target_chapters)
    )


@app.post("/api/episodes/{episode_id}/tick", response_model=LiveEpisode)
def tick(episode_id: str, request: TickRequest) -> LiveEpisode:
    return operate(lambda: orchestrator.tick(episode_id, elapsed_seconds=request.elapsed_seconds))


@app.post("/api/episodes/{episode_id}/heartbeat", response_model=LiveEpisode)
def heartbeat(episode_id: str) -> LiveEpisode:
    return operate(lambda: orchestrator.heartbeat(episode_id))


@app.post("/api/episodes/{episode_id}/seek", response_model=LiveEpisode)
def seek(episode_id: str, request: SeekRequest) -> LiveEpisode:
    return operate(lambda: orchestrator.seek(episode_id, request.position_seconds))


@app.post("/api/episodes/{episode_id}/commit/{segment_id}", response_model=LiveEpisode)
def commit(episode_id: str, segment_id: str) -> LiveEpisode:
    return operate(lambda: orchestrator.commit_segment(episode_id, segment_id))


@app.post("/api/episodes/{episode_id}/next", response_model=LiveEpisode)
def next_playable(episode_id: str) -> LiveEpisode:
    return operate(lambda: orchestrator.next_playable(episode_id))


@app.post("/api/episodes/{episode_id}/leave", response_model=LiveEpisode)
def leave(episode_id: str) -> LiveEpisode:
    return operate(lambda: orchestrator.leave(episode_id))


@app.post("/api/episodes/{episode_id}/pause", response_model=LiveEpisode)
def pause(episode_id: str) -> LiveEpisode:
    return operate(lambda: orchestrator.pause(episode_id))


@app.post("/api/episodes/{episode_id}/resume", response_model=LiveEpisode)
def resume(episode_id: str) -> LiveEpisode:
    return operate(lambda: orchestrator.resume(episode_id))


@app.post("/api/episodes/{episode_id}/materialize", response_model=LiveEpisode)
def materialize(episode_id: str) -> LiveEpisode:
    return operate(lambda: orchestrator.materialize_all(episode_id))


@app.post("/api/episodes/{episode_id}/replan", response_model=LiveEpisode)
def replan(episode_id: str, request: ReplaceRequest) -> LiveEpisode:
    return operate(lambda: orchestrator.replace_speculative_music(episode_id, request.title))
