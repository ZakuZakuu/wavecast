from __future__ import annotations

import asyncio
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from wavecast.assembly import EpisodeAssemblyError
from wavecast.intelligence.curation import CuratorContractError, ensure_distance_curve
from wavecast.intelligence.models import (
    ChapterPlan,
    NarrativeRole,
    NoveltyDistance,
    ProgramSkeleton,
)
from wavecast.intelligence.trace import GenerationTrace
from wavecast.providers.errors import (
    ProviderAuthenticationError,
    ProviderInvalidResponseError,
    ProviderOutputLimitError,
    ProviderRateLimitError,
    ProviderSchemaValidationError,
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
        (ProviderSchemaValidationError("structured response invalid"), "ProviderSchemaValidationError", "curator_schema_invalid"),
        (ProviderInvalidResponseError("provider response invalid"), "ProviderInvalidResponseError", "structured_output_invalid"),
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


def test_live_probe_forwards_bounded_duration_and_capacity() -> None:
    arguments = Namespace(
        topic="fixture topic",
        anchor=["Artist - Track"],
        desired_duration_seconds=1200,
        max_tracks=5,
        max_chapters=8,
    )

    request = live_episode_probe._assembly_request(arguments)

    assert request.topic == "fixture topic"
    assert request.anchor_tracks == ["Artist - Track"]
    assert request.desired_duration_seconds == 1200
    assert request.max_tracks == 5
    assert request.max_chapters == 8


def test_live_probe_rejects_non_positive_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "live_episode_probe.py",
            "--run-live",
            "--topic",
            "fixture topic",
            "--desired-duration-seconds",
            "0",
        ],
    )

    with pytest.raises(SystemExit):
        live_episode_probe.parse_args()


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
    with pytest.raises(CuratorContractError) as failure:
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


def test_curator_contract_report_preserves_safe_reason_and_snapshot() -> None:
    error = _wrapped(
        CuratorContractError(
            "contract failed",
            reason_code="curator_claim_support_scope_invalid",
            diagnostics=[{"chapter_index": 1, "reference_kind": "claim_support"}],
        )
    )
    error.reason_code = "curator_claim_support_scope_invalid"
    error.diagnostics = {
        "research_snapshot": {"research_plan_source": "fast_start"},
        "curator_diagnostics": [{"chapter_index": 1, "reference_kind": "claim_support"}],
    }

    report = live_episode_probe._failure_report(error, UsageLedger())

    assert report["cause_type"] == "CuratorContractError"
    assert report["reason_code"] == "curator_claim_support_scope_invalid"
    assert report["research_snapshot"] == {"research_plan_source": "fast_start"}
    assert "contract failed" not in json.dumps(report)


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
                max_chapters=16,
                json_output=report_path,
            )
        )
    )

    assert result == 1
    report = json.loads(report_path.read_text())
    assert report["reason_code"] == "provider_timeout"
    assert report["usage"]["input_tokens"] == 10
    assert report["usage_by_stage"]["curator"]["output_tokens"] == 20


def test_safe_trace_preserves_only_fallback_reason_type() -> None:
    trace = GenerationTrace(request_id="safe-trace")
    trace.mark(
        "background_research_plan_fallback",
        plan_source="generic_fallback",
        reason="TimeoutError",
        message="do not emit provider details",
    )
    result = type("Result", (), {"trace": trace})()

    report = live_episode_probe._safe_trace(result)

    assert report[-1]["metadata"] == {
        "plan_source": "generic_fallback",
        "reason": "TimeoutError",
    }
    assert "provider details" not in json.dumps(report)


def test_parse_args_defaults_max_chapters_to_application_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["live_episode_probe.py", "--topic", "fixture"])

    arguments = live_episode_probe.parse_args()

    assert arguments.max_tracks == 4
    assert arguments.max_chapters == 16


def test_live_probe_forwards_benchmark_max_chapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = live_episode_probe.ProviderSettings(mode="live")
    captured_requests: list[object] = []
    captured_settings: list[live_episode_probe.ProviderSettings] = []

    async def passing_preflight(*args: object, **kwargs: object) -> MusicPreflightResult:
        return MusicPreflightResult(ready=True, resolved_anchors=())

    class FakeAssembly:
        async def assemble(self, request: object, **kwargs: object) -> object:
            captured_requests.append(request)
            return object()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(live_episode_probe.ProviderSettings, "from_env", lambda: settings)
    monkeypatch.setattr(live_episode_probe, "preflight_music", passing_preflight)

    def create(configured: live_episode_probe.ProviderSettings) -> FakeAssembly:
        captured_settings.append(configured)
        return FakeAssembly()

    monkeypatch.setattr(live_episode_probe, "create_episode_assembly_service", create)
    monkeypatch.setattr(live_episode_probe, "_report", lambda result: {"status": "ok"})

    result = asyncio.run(
        live_episode_probe._run(
            Namespace(
                topic="fixture",
                anchor=[],
                max_tracks=4,
                max_chapters=6,
                json_output=tmp_path / "success.json",
            )
        )
    )

    assert result == 0
    assert len(captured_requests) == 1
    assert len(captured_settings) == 1
    assert captured_settings[0].max_attempts == 1
    assert captured_requests[0].max_tracks == 4
    assert captured_requests[0].max_chapters == 6
