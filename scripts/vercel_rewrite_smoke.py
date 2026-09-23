from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="apps/web/.next/routes-manifest.json")
    parser.add_argument("--expected", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    configured = manifest.get("rewrites", [])
    rewrites = (
        [entry for group in configured.values() for entry in group]
        if isinstance(configured, dict)
        else configured
    )
    if not any(
        isinstance(entry, dict)
        and entry.get("source") == "/api/:path*"
        and entry.get("destination") == args.expected
        for entry in rewrites
    ):
        raise SystemExit(f"expected /api/:path* rewrite to {args.expected!r}")
    print(f"vercel rewrite passed: /api/:path* -> {args.expected}")


if __name__ == "__main__":
    main()
