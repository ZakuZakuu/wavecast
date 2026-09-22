"""Server-only playback request details shared by proxy and snapshot paths."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ResolvedPlaybackRequest:
    """In-memory upstream request; never persist or expose this object."""

    provider: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
