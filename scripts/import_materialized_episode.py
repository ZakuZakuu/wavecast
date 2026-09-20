#!/usr/bin/env python3
"""Import a completed episode bundle into the existing WaveCast runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--web-url", default="http://127.0.0.1:3000")
    parser.add_argument("--listener-id")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    payload = json.loads(arguments.bundle.read_text(encoding="utf-8"))
    headers = {"Content-Type": "application/json"}
    if arguments.listener_id:
        headers["X-Wavecast-Listener"] = arguments.listener_id
    request = Request(
        f"{arguments.api_url.rstrip('/')}/api/episodes/from-materialized",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            imported = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        return 1

    episode_id = imported["id"]
    print(
        json.dumps(
            {
                "status": "ok",
                "episode_id": episode_id,
                "listen_url": f"{arguments.web_url.rstrip('/')}/episode/materialized/{episode_id}",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
