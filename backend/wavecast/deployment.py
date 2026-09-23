from __future__ import annotations

import os


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def resolve_audio_root(
    explicit_root: str | None = None,
    railway_mount_path: str | None = None,
    *,
    default: str = ".wavecast-data/audio",
) -> str:
    for candidate in (explicit_root, railway_mount_path, default):
        if candidate and candidate.strip():
            return candidate
    return default


def audio_root_from_env() -> str:
    return resolve_audio_root(
        os.getenv("WAVECAST_AUDIO_ROOT"),
        os.getenv("RAILWAY_VOLUME_MOUNT_PATH"),
    )
