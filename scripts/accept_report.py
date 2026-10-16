"""Digest an acceptance run directory into the numbers the report needs (no network)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


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
    print("\ncosts:", json.dumps(usage.get("costs"), ensure_ascii=False))
    print("meter:", json.dumps(summary.get("meter"), ensure_ascii=False))
    print("drive:", json.dumps(summary.get("drive"), ensure_ascii=False))
    print("collected:", json.dumps(summary.get("collected"), ensure_ascii=False)[:1500])
    rows = json.loads((run / "segments.json").read_text(encoding="utf-8"))
    print("\nsegments:")
    for r in rows:
        print(f"{r['order']:02d} {r['kind']:9s} {r['state']:12s} {'2host' if r['two_host'] else '     '} "
              f"{r['planned_seconds']}/{r['actual_seconds']}s {r['artist'] or ''} {r['title'] or ''}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
