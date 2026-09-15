"""One bounded, manually invoked progressive-intelligence probe."""

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

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

MAX_EXA_QUERIES = 2
MAX_TAVILY_QUERIES = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", action="append", required=True)
    parser.add_argument("--topic", default="guided listening around 3rd Coast")
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def require_live_settings() -> ProviderSettings:
    settings = ProviderSettings.from_env()
    if settings.mode != "live":
        raise ProviderConfigurationError(
            "set WAVECAST_PROVIDER_MODE=live in the local .env and run with uv --env-file"
        )
    return settings


def stage_summary(ledger: UsageLedger, stage: str) -> dict[str, object]:
    return ledger.totals_for_stage(stage).model_dump()


def sanitized_trace(trace: GenerationTrace) -> list[dict[str, object]]:
    """Expose timings and bounded counters only; never provider payloads."""
    allowed_keys = {"fallback", "candidate_count", "chapter_count", "query_count", "elapsed_ms"}
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


def sanitized_failure_reason(error: ProviderError) -> str:
    message = str(error)
    if message.startswith("invalid novelty curve values:"):
        return message
    if message.startswith("deepseek response was incomplete"):
        if "max_output_tokens" in message:
            return "incomplete:max_output_tokens"
        return "incomplete"
    return type(error).__name__


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


def sanitized_report(
    *,
    fast_result: object,
    background_result: object | None,
    ledger: UsageLedger,
    trace: GenerationTrace,
    fast_elapsed_ms: int,
    background_elapsed_ms: int | None,
    total_elapsed_ms: int,
) -> dict[str, object]:
    fast = fast_result
    background = background_result
    fast_plan = fast.plan  # type: ignore[attr-defined]
    fast_research = fast.research  # type: ignore[attr-defined]
    background_chapters = (
        [
            {
                "artist": chapter.track.artist,
                "title": chapter.track.title,
                "narrative_role": chapter.narrative_role.value,
                "novelty_distance": chapter.novelty_distance.value,
            }
            for chapter in background.skeleton.chapters
        ]
        if background
        else []
    )
    curator_end = "writer_started" if event_elapsed(trace, "writer_started") is not None else "program_skeleton_ready"
    report: dict[str, object] = {
        "fast_path": {
            "elapsed_ms": fast_elapsed_ms,
            "time_to_first_script_ms": trace.time_to_first_script_ms,
            "used_fallback": trace.fallback_used,
            "candidate_count": len(fast_plan.next_candidates),
            "first_script_characters": len(fast_plan.first_narration.text),
            "evidence_count": len(fast_research.bundle.evidence),
            "taste_dimensions": [
                hypothesis.dimension for hypothesis in fast_plan.immediate_taste_hypotheses
            ],
            "immediate_candidates": [
                f"{candidate.artist} — {candidate.title}"
                for candidate in fast_plan.next_candidates[:8]
            ],
        },
        "background": {
            "elapsed_ms": background_elapsed_ms,
            "completed": background is not None,
            "chapter_count": len(background.skeleton.chapters) if background else 0,  # type: ignore[attr-defined]
            "candidate_count": len(background.bundle.candidates) if background else 0,  # type: ignore[attr-defined]
            "curator_elapsed_ms": elapsed_between(trace, "curator_started", curator_end),
            "writer_elapsed_ms": elapsed_between(trace, "writer_started", "chapter_script_ready"),
            "chapters": background_chapters,
        },
        "usage": {
            "fast_research": stage_summary(ledger, "fast_research"),
            "fast_start": stage_summary(ledger, "fast_start"),
            "background_research": stage_summary(ledger, "background_research"),
            "curator": stage_summary(ledger, "curator"),
            "writer": stage_summary(ledger, "writer"),
        },
        "quality_summary": {
            "taste_dimensions": [
                hypothesis.dimension for hypothesis in fast_plan.immediate_taste_hypotheses
            ],
            "novelty_distance_curve": (
                [chapter.novelty_distance.value for chapter in background.skeleton.chapters]
                if background
                else []
            ),
            "candidate_names": (
                [
                    f"{candidate.artist} — {candidate.title}"
                    for candidate in fast_plan.next_candidates[:8]
                ]
                + (
                    [
                        f"{candidate.artist} — {candidate.title}"
                        for candidate in background.bundle.candidates[:8]  # type: ignore[attr-defined]
                    ]
                    if background
                    else []
                )
            ),
            "uncertainty_count": len(fast_plan.uncertainties)
            + (len(background.bundle.uncertainties) if background else 0),  # type: ignore[attr-defined]
        },
        "trace_event_count": len(trace.events),
        "total_elapsed_ms": total_elapsed_ms,
    }
    return report


async def run(anchors: list[str], topic: str) -> dict[str, object]:
    ledger = UsageLedger()
    exa: ExaSearchProvider | None = None
    tavily: TavilySearchProvider | None = None
    llm: DeepSeekLLMProvider | None = None
    trace = GenerationTrace(request_id="live-progressive-probe")
    stage = "fast_start"
    try:
        settings = replace(require_live_settings(), max_attempts=1)
        probe_started = perf_counter()
        exa = ExaSearchProvider(settings, ledger=ledger)
        tavily = TavilySearchProvider(settings, ledger=ledger)
        llm = DeepSeekLLMProvider(settings, ledger=ledger, max_attempts=1)
        request = FastResearchInput(
            topic=topic,
            anchor_tracks=anchors,
            desired_duration_seconds=1800,
        )
        fast_started = perf_counter()
        fast = FastPathCoordinator(
            research=FastResearchService(
                discovery=exa, research=tavily, ledger=ledger, deadline_seconds=4.5
            ),
            planner=FastStartPlanner(llm),
            deadline_seconds=15,
        )
        fast_result = await fast.run(request, request_id="live-progressive-probe")
        fast_elapsed_ms = int((perf_counter() - fast_started) * 1000)
        trace = fast_result.trace
        stage = "background_research"
        cancel_event = asyncio.Event()
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
            cancel_event=cancel_event,
            trace=trace,
        )
        background_elapsed_ms = int((perf_counter() - background_started) * 1000)
        report = sanitized_report(
            fast_result=fast_result,
            background_result=background_result,
            ledger=ledger,
            trace=trace,
            fast_elapsed_ms=fast_elapsed_ms,
            background_elapsed_ms=background_elapsed_ms,
            total_elapsed_ms=int((perf_counter() - probe_started) * 1000),
        )
        print("Progressive probe OK")
        print(f"FAST PATH: {json.dumps(report['fast_path'], sort_keys=True)}")
        print(f"BACKGROUND: {json.dumps(report['background'], sort_keys=True)}")
        print(f"USAGE: {json.dumps(report['usage'], sort_keys=True)}")
        print(f"QUALITY SUMMARY: {json.dumps(report['quality_summary'], ensure_ascii=False)}")
        print(f"TOTAL ELAPSED: {report['total_elapsed_ms']}ms")
        if report["fast_path"]["time_to_first_script_ms"] is not None:  # type: ignore[index]
            print(
                "TTFS: "
                f"{report['fast_path']['time_to_first_script_ms']}ms"  # type: ignore[index]
            )
        return report
    except ProviderError as error:
        # Diagnostics are deliberately metadata-only.  The provider error text can
        # contain vendor payloads, prompts, or other sensitive details.
        failure_stage = stage_from_trace(trace, stage)
        print("Progressive probe failed")
        print(
            "FAILURE: "
            + json.dumps(
                {
                    "stage": failure_stage,
                    "type": type(error).__name__,
                    "reason": sanitized_failure_reason(error),
                },
                sort_keys=True,
            )
        )
        print("TRACE: " + json.dumps(sanitized_trace(trace), sort_keys=True))
        print(
            "USAGE: "
            + json.dumps(
                {
                    stage_name: stage_summary(ledger, stage_name)
                    for stage_name in (
                        "fast_research",
                        "fast_start",
                        "background_research",
                        "curator",
                        "writer",
                    )
                },
                sort_keys=True,
            )
        )
        raise
    finally:
        if llm is not None:
            await llm.aclose()
        if tavily is not None:
            await tavily.aclose()
        if exa is not None:
            await exa.aclose()


if __name__ == "__main__":
    arguments = parse_args()
    try:
        result = asyncio.run(run(arguments.anchor, arguments.topic))
    except ProviderError:
        raise SystemExit(1)
    if arguments.json_output:
        arguments.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
