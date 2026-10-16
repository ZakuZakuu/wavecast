"""Digest an acceptance run directory into the numbers the report needs (no network)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def costs_line(label: str, costs: dict | None) -> str:
    """Known subtotals per currency plus the calls with no figure.  Never a total cost."""

    if not costs:
        return f"costs [{label}]: none recorded"
    cny, usd = costs.get("cny", {}), costs.get("usd", {})
    unknown = costs.get("unknown_calls", [])
    kinds: dict[str, int] = defaultdict(int)
    for call in unknown:
        kinds[f"{call.get('provider')}/{call.get('stage') or call.get('operation')}"] += 1
    return (
        f"costs [{label}]: known subtotal CNY {cny.get('estimated', 0):.3f} ({cny.get('priced_calls', 0)} priced calls)"
        f" + USD {usd.get('charged_or_estimated', 0):.3f} ({usd.get('priced_calls', 0)} priced calls); "
        f"{len(unknown)} calls with no figure, so NOT a total: {dict(kinds)}"
    )


def print_timing(run: Path, summary: dict, events: list[dict]) -> None:
    """The durations a run has, each with what it measures.  They overlap; none is 'generation time'."""

    timeline = [json.loads(line) for line in (run / "timeline.jsonl").read_text(encoding="utf-8").splitlines() if line]
    first = {}
    for e in timeline:
        first.setdefault(e["event"], e["t"])
    last = {e["event"]: e["t"] for e in timeline}
    published_complete = next((e["t"] for e in timeline if e["event"] == "published" and e.get("complete")), None)
    drive = summary.get("drive") or {}
    print("\ntiming (seconds; each measures something different and they overlap):")
    print(f"  whole script, start to collected files   {last.get('collected', 0):.0f}")
    print(f"  virtual listening (playhead clock)       {drive.get('listening_seconds')}")
    if published_complete is not None and "episode_started" in first:
        print(f"  episode start to fully published         {published_complete - first['episode_started']:.0f}")
    if "completed" in last and "collected" in last:
        print(f"  export (completed to collected)          {last['collected'] - last['completed']:.0f}")
    calls = sum((e.get("elapsed_ms") or 0) for e in events) / 1000
    print(f"  provider calls, summed (they run in parallel)  {calls:.0f}")
    print(f"  lease lost / recovered                   {drive.get('lease_lost')} / {drive.get('lease_recovered')}")
    for stall in drive.get("stalls", []):
        print(f"  stall at playhead {stall['start_playhead']}s lasted {stall['seconds']}s")


def main(run: Path) -> None:
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    usage = json.loads((run / "usage_before_restart.json").read_text(encoding="utf-8"))
    events = (usage.get("providers") or {}).get("provider_events", [])
    stages: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in events:
        key = (e.get("provider") or "?", e.get("stage") or e.get("operation") or "?", e.get("model") or "")
        row = stages[key]
        row["calls"] += 1
        row["ms"] += e.get("elapsed_ms") or 0
        row["in"] += e.get("input_tokens") or 0
        row["out"] += e.get("output_tokens") or 0
        row["audio_tokens"] += e.get("output_audio_tokens") or 0
        row["cny"] += e.get("estimated_cost_cny") or 0
        row["usd"] += e.get("actual_cost_usd") or e.get("estimated_cost_usd") or 0
        if e.get("outcome") not in (None, "ok"):
            row["not_ok"] += 1
    print("provider | stage | model | calls | seconds | in/out tokens | audio tok | CNY est | USD | not-ok")
    for (provider, stage, model), row in sorted(stages.items()):
        print(f"{provider} | {stage} | {model.split('-')[3] if model.startswith('doubao-seed') else model} | {int(row['calls'])} | "
              f"{row['ms'] / 1000:.1f} | {int(row['in'])}/{int(row['out'])} | {int(row['audio_tokens'])} | {row['cny']:.4f} | {row['usd']:.4f} | {int(row['not_ok'])}")
    print("\n" + costs_line("episode", usage.get("costs")))
    if usage.get("proposal"):
        print(costs_line("proposal (before the episode; not part of generating it)", usage["proposal"].get("costs")))
    print("meter:", json.dumps(summary.get("meter"), ensure_ascii=False))
    print("drive:", json.dumps(summary.get("drive"), ensure_ascii=False))
    print("collected:", json.dumps(summary.get("collected"), ensure_ascii=False)[:1500])
    print_timing(run, summary, events)
    rows = json.loads((run / "segments.json").read_text(encoding="utf-8"))
    print("\nsegments:")
    for r in rows:
        print(f"{r['order']:02d} {r['kind']:9s} {r['state']:12s} {'2host' if r['two_host'] else '     '} "
              f"{r['planned_seconds']}/{r['actual_seconds']}s {r['artist'] or ''} {r['title'] or ''}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
