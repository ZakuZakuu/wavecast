"""Small local object storage for browser-playable generated assets.

The provider-neutral storage seam deliberately has no knowledge of TTS or music.
Generated files live below ``.wavecast-data`` by default and are never part of the
source tree.  A later R2/S3 adapter can implement the same operations.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True)
class StoredObject:
    key: str
    content: bytes
    content_type: str
    metadata: dict[str, Any]


class LocalObjectStorageProvider:
    """Content-addressed local storage with safe lookup and browser URLs."""

    def __init__(
        self,
        root: str | Path = ".wavecast-data/audio",
        *,
        base_url: str = "/api/assets/audio",
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.base_url = base_url.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(
        self,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, content)
        manifest = path.with_name(f".{path.name}.json")
        self._atomic_write(
            manifest,
            json.dumps(
                {"content_type": content_type, "metadata": metadata or {}},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8"),
        )
        return self.url_for(key)

    async def get(self, key: str) -> StoredObject | None:
        path = self._path(key)
        if not path.is_file():
            return None
        manifest = path.with_name(f".{path.name}.json")
        content_type = "application/octet-stream"
        metadata: dict[str, Any] = {}
        if manifest.is_file():
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    configured_type = payload.get("content_type")
                    if isinstance(configured_type, str) and configured_type:
                        content_type = configured_type
                    configured_metadata = payload.get("metadata")
                    if isinstance(configured_metadata, dict):
                        metadata = configured_metadata
            except (OSError, ValueError):
                # A corrupt manifest must not expose the bytes with an unsafe type.
                return None
        try:
            content = path.read_bytes()
        except OSError:
            return None
        return StoredObject(
            key=key,
            content=content,
            content_type=content_type,
            metadata=metadata,
        )

    def url_for(self, key: str) -> str:
        self._path(key)
        return f"{self.base_url}/{quote(key, safe='')}"

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def _path(self, key: str) -> Path:
        if not key or Path(key).is_absolute() or any(part in {"", ".", ".."} for part in Path(key).parts):
            raise ValueError("storage key must be a relative path without traversal")
        candidate = (self.root / key).resolve()
        if self.root != candidate and self.root not in candidate.parents:
            raise ValueError("storage key escapes the configured root")
        return candidate

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
