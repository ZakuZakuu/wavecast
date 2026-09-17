from __future__ import annotations

import asyncio
import json
from argparse import Namespace
from pathlib import Path

import pytest
from wavecast.assembly import EpisodeAssemblyError
from wavecast.intelligence.curation import ensure_distance_curve
from wavecast.intelligence.models import (
    ChapterPlan,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
)
from wavecast.providers.errors import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderOutputLimitError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from wavecast.providers.usage import UsageEvent, UsageLedger

from scripts import live_episode_probe
from scripts.music_preflight import MusicPreflightResult


def _wrapped(cause: BaseException, *, stage: str = "curator") -> EpisodeAssemblyError:
    try:
        raise cause
    except BaseException as original:
        try:
            raise EpisodeAssemblyError("safe outer failure", stage=stage) from original
        except EpisodeAssemblyError as error:
            return error
    raise AssertionError("unreachable")


@pytest.mark.parametrize(
    ("cause", "cause_type", "reason_code"),
    [
        (ProviderTimeoutError("provider timed out"), "ProviderTimeoutError", "provider_timeout"),
        (ProviderRateLimitError("provider rate limited"), "ProviderRateLimitError", "provider_rate_limit"),
        (ProviderAuthenticationError("provider authentication failed"), "ProviderAuthenticationError", "provider_authentication"),
        (ProviderUnavailableError("provider unavailable"), "ProviderUnavailableError", "provider_unavailable"),
        (ProviderOutputLimitError("incomplete max output"), "ProviderOutputLimitError", "provider_output_limit"),
        (ProviderInvalidResponseError("structured response invalid"), "ProviderInvalidResponseError", "structured_output_invalid"),
    ],
)
def test_failure_report_classifies_curator_provider_failures(
    cause: BaseException, cause_type: str, reason_code: str
) -> None:
    report = live_episode_probe._failure_report(_wrapped(cause), UsageLedger())

    assert report["status"] == "failed"
    assert report["stage"] == "curator"
    assert report["error_type"] == "EpisodeAssemblyError"
    assert report["cause_type"] == cause_type
    assert report["reason_code"] == reason_code


def test_invalid_novelty_curve_is_classified_without_provider_text() -> None:
    valid = ProgramSkeleton(
        thesis="fixture",
        estimated_duration_seconds=120,
        chapters=[
            ChapterPlan(
                index=0,
                track=None,
                narrative_role=NarrativeRole.BRIDGE,
                reason="near",
                novelty_distance=NoveltyDistance.CLOSE,
                narration_goal="connect",
            ),
            ChapterPlan(
                index=1,
                track=None,
                narrative_role=NarrativeRole.DISCOVERY,
                reason="outward",
                novelty_distance=NoveltyDistance.DISCOVERY,
                narration_goal="open",
            ),
        ],
    )
    invalid = valid.model_copy(
        update={
            "chapters": [
                valid.chapters[0].model_copy(
                    update={"novelty_distance": NoveltyDistance.SURPRISE}
                ),
                valid.chapters[1].model_copy(
                    update={"novelty_distance": NoveltyDistance.BRIDGE}
                ),
            ]
        }
    )
    with pytest.raises(ProviderInvalidResponseError) as failure:
        ensure_distance_curve(invalid)

    report = live_episode_probe._failure_report(
        _wrapped(failure.value), UsageLedger()
    )

    assert report["reason_code"] == "curator_novelty_curve_invalid"
    assert "surprise" not in json.dumps(report)
    assert "invalid novelty curve values" not in json.dumps(report)


def test_failed_report_preserves_usage_and_only_safe_provider_event_fields() -> None:
    ledger = UsageLedger()
    ledger.record(
        UsageEvent(
            provider="deepseek",
            operation="structured",
            elapsed_ms=321,
            input_tokens=1200,
            output_tokens=2048,
            metadata={
                "stage": "curator",
                "model": "deepseek-test",
                "transport": "responses_json_schema",
                "finish_reason": "incomplete",
                "reasoning_tokens": 900,
                "prompt": "never emit this prompt",
                "response": "never emit this response",
            },
        )
    )

    report = live_episode_probe._failure_report(
        _wrapped(ProviderOutputLimitError("provider output limit")), ledger
    )
    serialized = json.dumps(report)

    assert report["usage"]["input_tokens"] == 1200
    assert report["usage"]["output_tokens"] == 2048
    assert report["usage"]["reasoning_tokens"] == 900
    assert report["usage_by_stage"]["curator"]["output_tokens"] == 2048
    assert report["provider_events"] == [
        {
            "provider": "deepseek",
            "operation": "structured",
            "stage": "curator",
            "elapsed_ms": 321,
            "input_tokens": 1200,
            "output_tokens": 2048,
            "usage_characters": None,
            "search_queries": None,
            "search_credits": None,
            "actual_cost_usd": None,
            "estimated_cost_usd": None,
            "model": "deepseek-test",
            "transport": "responses_json_schema",
            "finish_reason": "incomplete",
            "reasoning_tokens": 900,
        }
    ]
    assert "never emit" not in serialized
    assert "provider output limit" not in serialized


def test_unknown_failure_uses_stable_safe_diagnostics() -> None:
    report = live_episode_probe._failure_report(
        _wrapped(RuntimeError("secret arbitrary provider payload")), UsageLedger()
    )

    assert report["cause_type"] == "UnknownError"
    assert report["reason_code"] == "unknown_provider_failure"
    assert "secret arbitrary" not in json.dumps(report)


def test_failed_probe_writes_usage_diagnostics_from_assembly_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = UsageLedger()
    ledger.record(
        UsageEvent(
            provider="deepseek",
            operation="structured",
            elapsed_ms=17,
            input_tokens=10,
            output_tokens=20,
            metadata={"stage": "curator", "reasoning_tokens": 3},
        )
    )

    class FailingAssembly:
        def __init__(self) -> None:
            self.ledger = ledger

        async def assemble(self, *args: object, **kwargs: object) -> object:
            try:
                raise ProviderTimeoutError("timeout")
            except ProviderTimeoutError as cause:
                raise EpisodeAssemblyError("curator failed", stage="curator") from cause

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(
        live_episode_probe.ProviderSettings,
        "from_env",
        lambda: live_episode_probe.ProviderSettings(mode="live"),
    )

    async def passing_preflight(*args: object, **kwargs: object) -> MusicPreflightResult:
        return MusicPreflightResult(ready=True, resolved_anchors=())

    monkeypatch.setattr(live_episode_probe, "preflight_music", passing_preflight)
    monkeypatch.setattr(live_episode_probe, "create_episode_assembly_service", lambda _: FailingAssembly())
    report_path = tmp_path / "failure.json"

    result = asyncio.run(
        live_episode_probe._run(
            Namespace(
                topic="fixture",
                anchor=[],
                max_tracks=4,
                json_output=report_path,
            )
        )
    )

    assert result == 1
    report = json.loads(report_path.read_text())
    assert report["reason_code"] == "provider_timeout"
    assert report["usage"]["input_tokens"] == 10
    assert report["usage_by_stage"]["curator"]["output_tokens"] == 20
