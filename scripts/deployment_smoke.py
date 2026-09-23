from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LISTENER_ID = "deployment-smoke"
DEFAULT_SEED_ID = "city-pop-misunderstood"


def call(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
) -> tuple[Any, dict[str, str], int]:
    body = None
    headers = {"x-wavecast-listener": LISTENER_ID}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    request = Request(f"{base_url}{path}", data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            content = response.read()
            content_type = response.headers.get("content-type", "")
            if content_type.startswith("application/json"):
                return json.loads(content), dict(response.headers.items()), response.status
            return content, dict(response.headers.items()), response.status
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"deployment smoke request failed: {method} {path}") from error


def wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            payload, _, status = call(base_url, "/api/health")
            if status == 200 and isinstance(payload, dict) and payload.get("status") == "ok":
                return
        except RuntimeError:
            pass
        time.sleep(2)
    raise RuntimeError("deployment smoke health check timed out")


def main() -> None:
    parser = argparse.ArgumentParser(description="Credential-free production Compose smoke.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--seed-id", default=DEFAULT_SEED_ID)
    parser.add_argument("--restart-api", action="store_true")
    parser.add_argument("--compose-file", default="docker-compose.prod.yml")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    wait_for_health(base_url)

    seeds, _, _ = call(base_url, "/api/seeds")
    if not isinstance(seeds, list) or not seeds:
        raise RuntimeError("deployment smoke returned no episode seeds")

    episode, _, _ = call(
        base_url,
        f"/api/episodes/from-seed/{args.seed_id}",
        method="POST",
    )
    if not isinstance(episode, dict):
        raise RuntimeError("deployment smoke did not receive an episode")
    episode_id = episode.get("id")
    opening_segments = episode.get("segments")
    if not isinstance(episode_id, str) or not isinstance(opening_segments, list):
        raise RuntimeError("deployment smoke episode shape is invalid")
    if len(opening_segments) != 1:
        raise RuntimeError("progressive episode did not start with opening-only timeline")

    expanded, _, _ = call(
        base_url,
        f"/api/episodes/{episode_id}/ensure-buffer",
        method="POST",
        payload={"target_chapters": 1},
    )
    if not isinstance(expanded, dict):
        raise RuntimeError("deployment smoke buffer response is invalid")
    if "progressive_session" in expanded:
        raise RuntimeError("internal progressive session leaked through public API")
    timeline = expanded.get("segments")
    if not isinstance(timeline, list) or len(timeline) <= 1:
        raise RuntimeError("deployment smoke did not materialize a staged future")

    asset_urls = [
        segment.get("audio_source_url")
        for segment in timeline
        if isinstance(segment, dict)
        and isinstance(segment.get("audio_source_url"), str)
        and segment["audio_source_url"].startswith("/api/assets/audio/")
    ]
    if not asset_urls:
        raise RuntimeError("deployment smoke found no WaveCast-owned generated audio asset")
    for asset_url in asset_urls:
        content, headers, status = call(base_url, asset_url)
        if status != 200 or not isinstance(content, bytes) or not content:
            raise RuntimeError("deployment smoke audio asset was not playable")
        if not headers.get("content-type", "").startswith("audio/"):
            raise RuntimeError("deployment smoke audio asset had a non-audio content type")

    if args.restart_api:
        subprocess.run(
            ["docker", "compose", "-f", args.compose_file, "restart", "api"],
            check=True,
        )
        wait_for_health(base_url)
        resumed, _, _ = call(base_url, f"/api/episodes/{episode_id}")
        if not isinstance(resumed, dict) or resumed.get("id") != episode_id:
            raise RuntimeError("deployment smoke episode did not survive API restart")
        if not isinstance(resumed.get("segments"), list) or not resumed["segments"]:
            raise RuntimeError("deployment smoke lost persisted episode timeline")

    print(
        json.dumps(
            {
                "status": "passed",
                "seed_id": args.seed_id,
                "episode_id": episode_id,
                "opening_segment_count": len(opening_segments),
                "staged_segment_count": len(timeline),
                "owned_audio_asset_count": len(asset_urls),
                "api_restart_checked": args.restart_api,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
