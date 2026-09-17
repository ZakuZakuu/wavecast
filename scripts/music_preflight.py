"""Credential-free music-chain preflight for opt-in live probes.

This module is intentionally a probe boundary.  It verifies the local catalog
sidecar before any live research/LLM/TTS provider is constructed and resolves
explicit benchmark anchors through the same deterministic resolver used by
assembly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from wavecast.assembly import _build_music_registry
from wavecast.intelligence.models import ResolvedTrack, TrackProposal
from wavecast.intelligence.resolution import resolve_track_proposal_across_providers
from wavecast.providers.config import ProviderSettings
from wavecast.providers.errors import ProviderError
from wavecast.providers.registry import MusicProviderRegistry
from wavecast.providers.retrieval import MusicRetrievalService


class MusicPreflightError(ProviderError):
    """Safe reason why a live probe must not proceed."""


@dataclass(frozen=True)
class MusicPreflightResult:
    """Metadata-only outcome of the live probe music safety check."""

    ready: bool
    resolved_anchors: tuple[ResolvedTrack, ...]


def parse_anchor(value: str) -> TrackProposal:
    """Parse the probe's human-readable ``artist — title`` anchor format."""
    for separator in (" — ", " – ", " - "):
        if separator in value:
            artist, title = value.split(separator, 1)
            artist, title = artist.strip(), title.strip()
            if artist and title:
                return TrackProposal(
                    artist=artist,
                    title=title,
                    reasons=["live probe anchor preflight"],
                    confidence=1.0,
                )
    raise MusicPreflightError("music preflight rejected an anchor with no artist/title separator")


async def preflight_music(
    settings: ProviderSettings,
    anchor_tracks: Sequence[str],
    *,
    registry: MusicProviderRegistry | None = None,
    readiness_client: httpx.AsyncClient | None = None,
) -> MusicPreflightResult:
    """Check catalog readiness and resolve explicit anchors without AI providers.

    When a local NetEase sidecar is configured, ``/ready`` is the first check.
    The sidecar endpoint is deliberately separate from liveness and performs a
    bounded metadata-only upstream request.  The resolver check then confirms
    that each explicit anchor is actually playable through the normal catalog
    path.
    """
    owns_registry = registry is None
    try:
        configured_registry = registry or _build_music_registry(settings)
    except ProviderError as error:
        raise MusicPreflightError("music preflight has no usable catalog provider") from error
    try:
        if settings.netease_music_api_base_url:
            await _check_sidecar_readiness(
                settings.netease_music_api_base_url,
                settings.timeout_seconds,
                readiness_client=readiness_client,
            )
        elif not configured_registry.ordered():
            raise MusicPreflightError("music preflight has no configured catalog provider")

        retrieval = MusicRetrievalService(configured_registry)
        resolved: list[ResolvedTrack] = []
        for anchor in anchor_tracks:
            proposal = parse_anchor(anchor)
            track = await resolve_track_proposal_across_providers(retrieval, proposal)
            if track is None:
                raise MusicPreflightError(
                    f"music preflight could not resolve required anchor: {proposal.artist} — {proposal.title}"
                )
            resolved.append(track)

        if not anchor_tracks and not settings.netease_music_api_base_url:
            report = await retrieval.search_report("__wavecast_readiness__", limit=1)
            if report.failures:
                raise MusicPreflightError("music catalog provider failed readiness metadata query")
        return MusicPreflightResult(ready=True, resolved_anchors=tuple(resolved))
    finally:
        if owns_registry:
            await configured_registry.aclose()


async def _check_sidecar_readiness(
    base_url: str,
    timeout_seconds: float,
    *,
    readiness_client: httpx.AsyncClient | None,
) -> None:
    owns_client = readiness_client is None
    client = readiness_client or httpx.AsyncClient(
        timeout=timeout_seconds,
        trust_env=False,
    )
    try:
        try:
            response = await client.get(f"{base_url.rstrip('/')}/ready")
        except httpx.TimeoutException as error:
            raise MusicPreflightError("music sidecar readiness timed out") from error
        except httpx.RequestError as error:
            raise MusicPreflightError("music sidecar readiness is unavailable") from error
        if response.status_code != 200:
            raise MusicPreflightError(
                f"music sidecar readiness failed with HTTP {response.status_code}"
            )
    finally:
        if owns_client:
            await client.aclose()
