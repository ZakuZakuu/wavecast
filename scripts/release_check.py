"""Read-only check that a deployment serves the new programme-link routes.

Nothing is generated and nothing is written, so it is safe against production:

    python scripts/release_check.py https://wavecast.space
    python scripts/release_check.py https://wavecast.up.railway.app --api-only   # the API alone, before the web

Exit status 0 only when every check passes. The API checks tell "the new backend is live" apart
from "the old backend is still answering": the old one has none of these routes.
"""

from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BUILT_IN = "city-pop-misunderstood"


def fetch(base: str, path: str) -> tuple[int, str]:
    request = Request(f"{base}{path}", headers={"x-wavecast-listener": "release-check"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (URLError, TimeoutError) as error:
        return 0, str(error)


def main() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    api_only = "--api-only" in sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        return 2
    base = args[0].rstrip("/")
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    status, body = fetch(base, "/api/health")
    check("API health", status == 200, f"HTTP {status}")

    status, body = fetch(base, f"/api/programs/{BUILT_IN}/public")
    public_ok = False
    if status == 200:
        try:
            data = json.loads(body)
            public_ok = data.get("id") == BUILT_IN and "topic" not in data
        except ValueError:
            pass
    check("public programme read (new API)", public_ok, f"HTTP {status}")

    status, _ = fetch(base, "/api/programs/by-code/0000000000")
    check("short-code lookup answers 404 for an unknown code (new API)", status == 404, f"HTTP {status}")

    status, _ = fetch(base, "/api/programs/not-a-programme/public")
    check("unknown programme is a plain 404", status == 404, f"HTTP {status}")

    if not api_only:
        status, page = fetch(base, f"/program/{BUILT_IN}")
        check("web: programme page unfurls its title", status == 200 and 'property="og:title"' in page, f"HTTP {status}")
        status, _ = fetch(base, "/p/0000000000")
        check("web: unknown short link does not error", status in {200, 307, 308}, f"HTTP {status}")

    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"{'ok  ' if ok else 'FAIL'} {name.ljust(width)}  {detail}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
