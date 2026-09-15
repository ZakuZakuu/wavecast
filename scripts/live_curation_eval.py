"""Run at most two bounded, opt-in Guided Discovery quality evaluations."""

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from wavecast.evals import GUIDED_DISCOVERY_CASES, GuidedDiscoveryCase, build_review_bundle
from wavecast.intelligence.background import BackgroundIntelligencePipeline
from wavecast.intelligence.curation import CuratorService
from wavecast.intelligence.fast_start import FastPathCoordinator, FastStartPlanner
from wavecast.intelligence.models import FastResearchInput
from wavecast.intelligence.research import BackgroundResearchService, FastResearchService
from wavecast.intelligence.trace import GenerationTrace
from wavecast.intelligence.writer import WriterService
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderConfigurationError, ProviderError
from wavecast.providers.search import ExaSearchProvider, TavilySearchProvider
from wavecast.providers.usage import UsageLedger

MAX_CASES = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        action="append",
        choices=[case.case_id for case in GUIDED_DISCOVERY_CASES],
        help="case ID; defaults to the first two benchmark cases",
    )
    parser.add_argument("--json-output", type=Path)
    arguments = parser.parse_args()
    if arguments.case and len(arguments.case) > MAX_CASES:
        parser.error(f"at most {MAX_CASES} cases are allowed")
    return arguments


def require_live_settings() -> ProviderSettings:
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        raise ProviderConfigurationError(
            "set WAVECAST_PROVIDER_MODE=live in the local .env and run with uv --env-file"
        )
    return settings


def event_elapsed(trace: GenerationTrace, name: str) -> int | None:
    for event in trace.events:
        if event.name == name:
            return event.elapsed_from_start_ms
    return None


def elapsed_between(trace: GenerationTrace, start: str, end: str) -> int | None:
    started = event_elapsed(trace, start)
    finished = event_elapsed(trace, end)
    if started is None or finished is None:
        return None
    return max(0, finished - started)


def stage_from_trace(trace: GenerationTrace, current: str) -> str:
    names = {event.name for event in trace.events}
    if "writer_started" in names:
        return "writer"
    if "curator_started" in names:
        return "curator"
    if "background_research_started" in names or "background_started" in names:
        return "background_research"
    if "first_script_ready" in names or "fallback_used" in names:
        return "fast_start"
    return current


def sanitized_trace(trace: GenerationTrace) -> list[dict[str, object]]:
    allowed_keys = {"fallback", "candidate_count", "chapter_count", "query_count"}
    return [
        {
            "name": event.name,
            "elapsed_ms": event.elapsed_from_start_ms,
            "metadata": {
                key: value for key, value in event.metadata.items() if key in allowed_keys
            },
        }
        for event in trace.events
    ]


def stage_usage(ledger: UsageLedger) -> dict[str, dict[str, object]]:
    return {
        stage: ledger.totals_for_stage(stage).model_dump()
        for stage in (
            "fast_research",
            "fast_start",
            "background_research",
            "curator",
            "writer",
        )
    }


def sanitized_failure_reason(error: ProviderError) -> str:
    message = str(error)
    if message.startswith("invalid novelty curve values:"):
        return message
    if message.startswith("deepseek response was incomplete"):
        if "max_output_tokens" in message:
            return "incomplete:max_output_tokens"
        return "incomplete"
    return type(error).__name__


async def evaluate_case(case: GuidedDiscoveryCase, settings: ProviderSettings) -> dict[str, object]:
    ledger = UsageLedger()
    exa: ExaSearchProvider | None = None
    tavily: TavilySearchProvider | None = None
    llm: DeepSeekLLMProvider | None = None
    trace = GenerationTrace(request_id=f"live-curation-eval:{case.case_id}")
    stage = "fast_start"
    started = perf_counter()
    try:
        exa = ExaSearchProvider(settings, ledger=ledger)
        tavily = TavilySearchProvider(settings, ledger=ledger)
        llm = DeepSeekLLMProvider(settings, ledger=ledger, max_attempts=1)
        request = FastResearchInput(
            topic=case.topic,
            anchor_tracks=case.anchor_tracks,
            anchor_artists=case.anchor_artists,
            desired_duration_seconds=case.desired_duration_seconds,
        )
        fast_started = perf_counter()
        fast_result = await FastPathCoordinator(
            research=FastResearchService(
                discovery=exa, research=tavily, ledger=ledger, deadline_seconds=4.5
            ),
            planner=FastStartPlanner(llm),
            deadline_seconds=15,
        ).run(request, request_id=f"live-curation-eval:{case.case_id}")
        fast_elapsed_ms = int((perf_counter() - fast_started) * 1000)
        trace = fast_result.trace

        stage = "background_research"
        background_started = perf_counter()
        background_result = await BackgroundIntelligencePipeline(
            research=BackgroundResearchService(
                discovery=exa, research=tavily, ledger=ledger, deadline_seconds=8
            ),
            curator=CuratorService(llm),
            writer=WriterService(llm),
        ).run(
            request,
            fast_result,
            cancel_event=asyncio.Event(),
            trace=trace,
        )
        background_elapsed_ms = int((perf_counter() - background_started) * 1000)
        review = build_review_bundle(case, fast_result.plan, background_result.skeleton if background_result else None)
        curator_end = (
            "writer_started"
            if event_elapsed(trace, "writer_started") is not None
            else "program_skeleton_ready"
        )
        return {
            "case_id": case.case_id,
            "case_title": case.title,
            "fast": {
                "fallback": trace.fallback_used,
                "ttfs_ms": trace.time_to_first_script_ms,
                "elapsed_ms": fast_elapsed_ms,
                "taste_dimensions": [
                    hypothesis.dimension for hypothesis in fast_result.plan.immediate_taste_hypotheses
                ],
                "immediate_candidates": [
                    f"{candidate.artist} — {candidate.title}"
                    for candidate in fast_result.plan.next_candidates
                ],
            },
            "background": {
                "elapsed_ms": background_elapsed_ms,
                "curator_elapsed_ms": elapsed_between(trace, "curator_started", curator_end),
                "writer_elapsed_ms": elapsed_between(
                    trace, "writer_started", "chapter_script_ready"
                ),
                "chapters": [chapter.model_dump(mode="json") for chapter in review.program_arc],
            },
            "review": review.model_dump(mode="json"),
            "usage": stage_usage(ledger),
            "total_elapsed_ms": int((perf_counter() - started) * 1000),
        }
    except ProviderError as error:
        failure_stage = stage_from_trace(trace, stage)
        print("Guided Discovery evaluation failed")
        print(
            "FAILURE: "
            + json.dumps(
                {
                    "case_id": case.case_id,
                    "stage": failure_stage,
                    "type": type(error).__name__,
                    "reason": sanitized_failure_reason(error),
                },
                sort_keys=True,
            )
        )
        print("TRACE: " + json.dumps(sanitized_trace(trace), sort_keys=True))
        print("USAGE: " + json.dumps(stage_usage(ledger), sort_keys=True))
        raise
    finally:
        if llm is not None:
            await llm.aclose()
        if tavily is not None:
            await tavily.aclose()
        if exa is not None:
            await exa.aclose()


async def run(case_ids: list[str] | None = None) -> list[dict[str, object]]:
    settings = replace(require_live_settings(), max_attempts=1)
    selected_ids = case_ids or [case.case_id for case in GUIDED_DISCOVERY_CASES[:MAX_CASES]]
    cases = [case for case in GUIDED_DISCOVERY_CASES if case.case_id in selected_ids]
    reports: list[dict[str, object]] = []
    for case in cases:
        report = await evaluate_case(case, settings)
        reports.append(report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return reports


if __name__ == "__main__":
    arguments = parse_args()
    try:
        reports = asyncio.run(run(arguments.case))
    except ProviderError:
        raise SystemExit(1)
    if arguments.json_output:
        arguments.json_output.write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )
