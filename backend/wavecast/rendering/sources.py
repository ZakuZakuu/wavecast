from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from wavecast.arrangement.models import MixPlan
from wavecast.rendering.errors import MixSourceUnavailableError

if TYPE_CHECKING:
    from wavecast.providers.contracts import ObjectStorageProvider


async def resolve_mix_sources(
    plan: MixPlan,
    storage: ObjectStorageProvider,
    directory: Path,
) -> dict[str, Path]:
    """Materialize only WaveCast-owned storage URLs for a bounded ffmpeg run."""
    directory.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, Path] = {}
    for index, clip in enumerate(plan.clips):
        parsed = urlparse(clip.source_url)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise MixSourceUnavailableError("mix source is not a safe owned asset")
        prefix = "/api/assets/audio/"
        if not parsed.path.startswith(prefix):
            raise MixSourceUnavailableError("mix source is not a WaveCast-owned asset")
        key = unquote(parsed.path[len(prefix):])
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise MixSourceUnavailableError("mix source key is unsafe")
        try:
            stored = await storage.get(key)
        except (OSError, ValueError) as error:
            raise MixSourceUnavailableError("mix source is unavailable") from error
        if stored is None or not stored.content:
            raise MixSourceUnavailableError("mix source is unavailable")
        suffix = Path(key).suffix if Path(key).suffix else ".audio"
        filename = f"{index:04d}-{hashlib.sha256(clip.id.encode()).hexdigest()[:12]}{suffix}"
        path = directory / filename
        path.write_bytes(stored.content)
        resolved[clip.id] = path
    return resolved


__all__ = ["resolve_mix_sources"]
