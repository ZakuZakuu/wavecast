"""Run the fixed narration scenes through the Writer and report deterministic checks.

usage: uv run python scripts/eval_narration.py [--samples 3] [--label baseline]
                                              [--scenes id1,id2] [--out DIR]

Calls the configured DeepSeek model (paid, text only; no TTS).  Prints and saves counts and the
generated copy; never prints keys or request headers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from wavecast.evals.narration_checks import CHARS_PER_SECOND, BatchSummary, check_block, summarize
from wavecast.evals.narration_scenes import SCENES, NarrationScene
from wavecast.intelligence.models import OutputLanguage, RadioScript
from wavecast.intelligence.writer import WriterService
from wavecast.presentation import HostMode
from wavecast.providers.config import ProviderSettings
from wavecast.providers.deepseek import DeepSeekLLMProvider
from wavecast.providers.errors import ProviderError
from wavecast.providers.profiles import InferenceProfile
from wavecast.providers.usage import UsageLedger, usage_diagnostics
from wavecast.spoken_form import KnownTrack


async def run_scene(
    writer: WriterService, scene: NarrationScene, sample: int
) -> list[dict[str, object]]:
    tracks = [
        KnownTrack(artist=track.canonical_artist, title=track.canonical_title)
        for track in (scene.just_played, scene.upcoming)
        if track is not None
    ]
    try:
        script = await writer.write(
            scene.chapter(),
            scene.evidence(),
            previous_committed_context=scene.previous_context,
            host_mode=HostMode.LIGHT,
            target_duration_seconds=scene.window_seconds,
            output_language=OutputLanguage.ZH_CN,
            topic=scene.topic,
            slot_context=scene.slot(),
            inference_profile=InferenceProfile.FAST,
        )
    except ProviderError as error:
        return [
            {
                "scene": scene.scene_id,
                "sample": sample,
                "error": f"{type(error).__name__}: {str(error)[:160]}",
            }
        ]
    if not isinstance(script, RadioScript):
        return [{"scene": scene.scene_id, "sample": sample, "error": "unexpected_output"}]
    rows: list[dict[str, object]] = []
    for block in script.blocks:
        check = check_block(
            block.text,
            tts_text=block.tts_text,
            window_seconds=scene.window_seconds,
            chars_per_second=CHARS_PER_SECOND,
            tracks=tracks,
            is_final=scene.is_final,
        )
        rows.append(
            {
                "scene": scene.scene_id,
                "sample": sample,
                "kind": block.kind.value,
                "text": block.text,
                "tts_text": block.tts_text,
                "issues": check.issues,
                "figurative": check.figurative_hits,
                "opener": check.opener,
                "seconds": round(check.estimated_seconds, 1),
                "window": scene.window_seconds,
            }
        )
    return rows


def render_report(label: str, rows: list[dict[str, object]], summary: BatchSummary) -> str:
    lines = [f"# Narration eval: {label}", ""]
    lines.append(
        f"blocks {summary.blocks} | opener kinds {summary.opener_kinds} "
        f"(diversity {summary.opener_diversity:.2f}) | most common opener "
        f"“{summary.most_common_opener}” {summary.most_common_opener_share:.0%} | "
        f"AI-flavoured {summary.ai_flavour_rate:.0%} | listen-cue {summary.listen_cue_rate:.0%} | "
        f"mean {summary.mean_seconds:.1f}s"
    )
    lines.append(f"issues: {json.dumps(summary.issue_counts, ensure_ascii=False)}")
    lines.append("")
    for row in rows:
        if "error" in row:
            lines.append(f"- {row['scene']}#{row['sample']}: ERROR {row['error']}")
            continue
        flag = f"  ⚠ {', '.join(map(str, row['issues']))}" if row["issues"] else ""
        lines.append(f"- {row['scene']}#{row['sample']} [{row['kind']}] ({row['seconds']}s/{row['window']}s){flag}")
        lines.append(f"    {row['text']}")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--scenes", default="")
    parser.add_argument("--out", default=".wavecast-data/narration-eval")
    args = parser.parse_args()

    settings = ProviderSettings.from_env()
    ledger = UsageLedger()
    llm = DeepSeekLLMProvider(settings, ledger=ledger, max_attempts=1)
    writer = WriterService(llm)
    wanted = {item for item in args.scenes.split(",") if item}
    scenes = [scene for scene in SCENES if not wanted or scene.scene_id in wanted]

    rows: list[dict[str, object]] = []
    for scene in scenes:
        results = await asyncio.gather(*(run_scene(writer, scene, i + 1) for i in range(args.samples)))
        for result in results:
            rows.extend(result)
    ok = [row for row in rows if "error" not in row]
    checks = [
        check_block(
            str(row["text"]),
            tts_text=row["tts_text"] if isinstance(row["tts_text"], str) else None,
            window_seconds=float(row["window"]),  # type: ignore[arg-type]
            chars_per_second=CHARS_PER_SECOND,
        )
        for row in ok
    ]
    summary = summarize(checks)
    report = render_report(args.label, rows, summary)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.label}.json").write_text(
        json.dumps({"summary": asdict(summary), "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / f"{args.label}.md").write_text(report, encoding="utf-8")
    print(report)
    usage = usage_diagnostics(ledger)["usage"]
    print(f"\nprovider calls: {usage['event_count']}, input tokens {usage['input_tokens']}, "
          f"output tokens {usage['output_tokens']}")


if __name__ == "__main__":
    asyncio.run(main())
