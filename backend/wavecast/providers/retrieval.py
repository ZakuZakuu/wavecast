"""Provider-neutral, deterministic music retrieval and version grouping."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .contracts import MusicProvider, TrackMetadata
from .errors import ProviderError
from .registry import MusicProviderRegistry


class VersionKind(StrEnum):
    UNKNOWN = "unknown"
    STUDIO = "studio"
    LIVE = "live"
    REMIX = "remix"
    ACOUSTIC = "acoustic"
    OST = "ost"
    RADIO_EDIT = "radio_edit"


class RetrievedTrack(BaseModel):
    """A catalog result with provenance and explicit version evidence."""

    provider: str = Field(min_length=1)
    track_ref: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    title: str = Field(min_length=1)
    base_title: str | None = None
    album: str | None = None
    duration_seconds: int = Field(ge=0)
    playable: bool
    version_kind: VersionKind = VersionKind.UNKNOWN
    version_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    ranking_reasons: list[str] = Field(default_factory=list)

    @staticmethod
    def version_for(title: str, metadata: dict[str, Any]) -> tuple[VersionKind, str | None, str]:
        """Classify only explicit version evidence and return the base title."""
        explicit_kind = _explicit_version_kind(metadata)
        explicit_label = _string_value(metadata.get("version_label"))
        if explicit_kind is not None:
            return explicit_kind, explicit_label, _strip_version_suffix(title)

        match = re.search(r"\s*[\(\[]([^\)\]]+)[\)\]]\s*$", title)
        if match:
            label = match.group(1).strip()
            kind = _version_kind_for_label(label)
            if kind is not VersionKind.UNKNOWN:
                return kind, label, title[: match.start()].strip()

        match = re.search(
            r"\s+-\s+(remix|acoustic|live(?:\s+.*)?|radio\s+edit)\s*$",
            title,
            re.IGNORECASE,
        )
        if match:
            label = match.group(1).strip()
            return _version_kind_for_label(label), label, title[: match.start()].strip()
        return VersionKind.UNKNOWN, explicit_label, title

    @classmethod
    def from_metadata(cls, provider: str, metadata: TrackMetadata) -> RetrievedTrack:
        version_kind, version_label, base_title = cls.version_for(
            metadata.title, metadata.metadata
        )
        return cls(
            provider=provider,
            track_ref=metadata.track_ref,
            artist=metadata.artist,
            title=metadata.title,
            base_title=base_title,
            album=_string_value(metadata.metadata.get("album")),
            duration_seconds=metadata.duration_seconds,
            playable=metadata.playable,
            version_kind=version_kind,
            version_label=version_label,
            metadata=dict(metadata.metadata),
            ranking_reasons=[],
        )

    @property
    def group_key(self) -> str:
        return "|".join(
            (
                _normalize_text(self.artist),
                _normalize_text(self.base_title or self.title),
                self.version_kind.value,
                _normalize_text(self.version_label or ""),
            )
        )


class RetrievedTrackGroup(BaseModel):
    group_key: str
    candidates: list[RetrievedTrack]


class RetrievalFailure(BaseModel):
    provider: str
    kind: str
    message: str


class RetrievalReport(BaseModel):
    query: str
    candidates: list[RetrievedTrack]
    groups: list[RetrievedTrackGroup]
    failures: list[RetrievalFailure] = Field(default_factory=list)


class MusicRetrievalService:
    """Fan out catalog searches while keeping ranking and failures deterministic."""

    def __init__(
        self,
        registry: MusicProviderRegistry,
        *,
        per_provider_timeout_seconds: float = 2.0,
    ) -> None:
        if per_provider_timeout_seconds <= 0:
            raise ValueError("per_provider_timeout_seconds must be positive")
        self.registry = registry
        self.per_provider_timeout_seconds = per_provider_timeout_seconds

    async def search(
        self,
        query: str,
        *,
        requested_artist: str | None = None,
        requested_title: str | None = None,
        requested_version: VersionKind | None = None,
        limit: int = 10,
    ) -> list[RetrievedTrack]:
        return (
            await self.search_report(
                query,
                requested_artist=requested_artist,
                requested_title=requested_title,
                requested_version=requested_version,
                limit=limit,
            )
        ).candidates

    async def search_report(
        self,
        query: str,
        *,
        requested_artist: str | None = None,
        requested_title: str | None = None,
        requested_version: VersionKind | None = None,
        limit: int = 10,
    ) -> RetrievalReport:
        if limit <= 0:
            return RetrievalReport(query=query, candidates=[], groups=[])
        ordered = self.registry.ordered()
        results = await asyncio.gather(
            *(
                self._search_provider(provider_name, provider, query, limit)
                for provider_name, provider in ordered
            )
        )
        candidates: list[RetrievedTrack] = []
        failures: list[RetrievalFailure] = []
        for provider_index, (provider_name, provider_result, failure) in enumerate(results):
            del provider_index
            if failure is not None:
                failures.append(failure)
            candidates.extend(
                self._normalize_results(provider_name, provider_result, failures)
            )

        ranked = self._rank(
            candidates,
            requested_artist=requested_artist,
            requested_title=requested_title,
            requested_version=requested_version,
            provider_names=[name for name, _provider in ordered],
        )
        selected_group_keys = {candidate.group_key for candidate in ranked[:limit]}
        selected = [candidate for candidate in ranked if candidate.group_key in selected_group_keys]
        groups = _group_candidates(selected)
        return RetrievalReport(
            query=query,
            candidates=selected,
            groups=groups,
            failures=failures,
        )

    async def _search_provider(
        self,
        provider_name: str,
        provider: MusicProvider,
        query: str,
        limit: int,
    ) -> tuple[str, list[TrackMetadata], RetrievalFailure | None]:
        try:
            result = await asyncio.wait_for(
                provider.search(query, limit=limit), self.per_provider_timeout_seconds
            )
            if not isinstance(result, list):
                return (
                    provider_name,
                    [],
                    RetrievalFailure(
                        provider=provider_name,
                        kind="malformed_result",
                        message="provider returned a non-list result",
                    ),
                )
            return provider_name, result, None
        except TimeoutError:
            return (
                provider_name,
                [],
                RetrievalFailure(
                    provider=provider_name,
                    kind="timeout",
                    message="provider search exceeded its bounded timeout",
                ),
            )
        except ProviderError as error:
            return (
                provider_name,
                [],
                RetrievalFailure(provider=provider_name, kind="provider_error", message=str(error)),
            )
        except Exception:
            return (
                provider_name,
                [],
                RetrievalFailure(
                    provider=provider_name,
                    kind="provider_error",
                    message="provider search failed",
                ),
            )

    @staticmethod
    def _normalize_results(
        provider_name: str,
        results: list[TrackMetadata],
        failures: list[RetrievalFailure],
    ) -> list[RetrievedTrack]:
        normalized: list[RetrievedTrack] = []
        for result in results:
            try:
                metadata = (
                    result
                    if isinstance(result, TrackMetadata)
                    else TrackMetadata.model_validate(result)
                )
                normalized.append(RetrievedTrack.from_metadata(provider_name, metadata))
            except (ValidationError, TypeError, ValueError):
                failures.append(
                    RetrievalFailure(
                        provider=provider_name,
                        kind="malformed_result",
                        message="provider returned invalid track metadata",
                    )
                )
        return normalized

    @staticmethod
    def _rank(
        candidates: list[RetrievedTrack],
        *,
        requested_artist: str | None,
        requested_title: str | None,
        requested_version: VersionKind | None,
        provider_names: Sequence[str],
    ) -> list[RetrievedTrack]:
        artist = _normalize_text(requested_artist or "")
        title = _normalize_text(requested_title or "")
        provider_priority = {
            name.casefold(): len(provider_names) - index
            for index, name in enumerate(provider_names)
        }
        for candidate in candidates:
            reasons = list(candidate.ranking_reasons)
            score = 0.0
            if artist and _normalize_text(candidate.artist) == artist:
                score += 100
                reasons.append("exact_artist")
            if title and _normalize_text(candidate.title) == title:
                score += 80
                reasons.append("exact_title")
            elif title and _normalize_text(candidate.base_title or candidate.title) == title:
                score += 55
                reasons.append("base_title_match")
            if candidate.playable:
                score += 20
                reasons.append("playable")
            if requested_version is not None and candidate.version_kind is requested_version:
                score += 30
                reasons.append("requested_version_match")
            score += provider_priority.get(candidate.provider.casefold(), 0)
            reasons.append("provider_priority")
            if candidate.album:
                score += 3
                reasons.append("album_metadata")
            if candidate.duration_seconds > 0:
                score += 2
                reasons.append("duration_metadata")
            candidate.score = score
            candidate.ranking_reasons = reasons
        return sorted(
            candidates,
            key=lambda candidate: (
                -candidate.score,
                _normalize_text(candidate.artist),
                _normalize_text(candidate.base_title or candidate.title),
                candidate.version_kind.value,
                _normalize_text(candidate.version_label or ""),
                candidate.provider.casefold(),
                candidate.track_ref,
            ),
        )


def _group_candidates(candidates: list[RetrievedTrack]) -> list[RetrievedTrackGroup]:
    grouped: dict[str, list[RetrievedTrack]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.group_key, []).append(candidate)
    return [RetrievedTrackGroup(group_key=key, candidates=items) for key, items in grouped.items()]


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).split())


def _string_value(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _explicit_version_kind(metadata: dict[str, Any]) -> VersionKind | None:
    if metadata.get("soundtrack") or metadata.get("ost"):
        return VersionKind.OST
    value = _string_value(metadata.get("version_kind"))
    if value:
        normalized = value.casefold().replace("-", "_").replace(" ", "_")
        try:
            return VersionKind(normalized)
        except ValueError:
            return None
    return None


def _version_kind_for_label(label: str) -> VersionKind:
    normalized = _normalize_text(label)
    if normalized.startswith("live"):
        return VersionKind.LIVE
    if "remix" in normalized:
        return VersionKind.REMIX
    if "acoustic" in normalized:
        return VersionKind.ACOUSTIC
    if "radio edit" in normalized or normalized == "radio":
        return VersionKind.RADIO_EDIT
    if "soundtrack" in normalized or normalized == "ost":
        return VersionKind.OST
    return VersionKind.UNKNOWN


def _strip_version_suffix(title: str) -> str:
    return re.sub(r"\s*[\(\[][^\)\]]+[\)\]]\s*$", "", title).strip()
