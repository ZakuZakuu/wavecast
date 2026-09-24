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
    configured = manifest.get("rewrites", {})
    fallback = configured.get("fallback", []) if isinstance(configured, dict) else []
    if not any(
        isinstance(entry, dict)
        and entry.get("source") == "/api/:path*"
        and entry.get("destination") == args.expected
        for entry in fallback
    ):
        raise SystemExit(f"expected fallback /api/:path* rewrite to {args.expected!r}")
    dynamic_routes = manifest.get("dynamicRoutes", [])
    if not any(
        isinstance(route, dict)
        and route.get("page") == "/api/auth/[...all]"
        for route in dynamic_routes
    ):
        raise SystemExit("expected Next.js filesystem route /api/auth/[...all]")
    print(f"vercel rewrite passed: /api/:path* -> {args.expected}")
    print("auth route precedence passed: /api/auth/[...all] is a Next.js filesystem route")


if __name__ == "__main__":
    main()
