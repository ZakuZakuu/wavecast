#!/usr/bin/env python3
"""Preview three fixed scripts, or explicitly opt into three paid podcast syntheses.

No programme, Writer, database or hosted service is involved. Listen to the local WAVs;
a successful response does not establish that an English word was pronounced correctly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from wavecast.models.dialogue import DialogueSpeaker
from wavecast.providers.doubao_podcast import (
    DOUBAO_PODCAST_RESOURCE_ID,
    DoubaoPodcastSpeechProvider,
    DoubaoPodcastWebSocketTransport,
)
from wavecast.providers.doubao_voices import SPEECH_RATE_B, VOICE_COMBINATION_B
from wavecast.providers.errors import ProviderError
from wavecast.providers.speech import SpeechRequest, SpeechTurn
from wavecast.storage import LocalObjectStorageProvider

CASES = {
    "uppercase": ("NO MUSIC, NO LIFE?", "NO LIFE NO MUSIC"),
    "sentence-case": ("No music, no life?", "No life no music"),
    "lowercase": ("no music, no life?", "no life no music"),
}


def requests() -> dict[str, SpeechRequest]:
    return {
        label: SpeechRequest(
            turns=[
                SpeechTurn(
                    speaker=DialogueSpeaker.A,
                    text=f"把海报上的那句“{first}”反过来写成“{second}”。",
                ),
                SpeechTurn(speaker=DialogueSpeaker.B, text="这样就把生命放在了音乐前面。"),
            ],
            roles=list(VOICE_COMBINATION_B),
            speed=float(SPEECH_RATE_B),
            audio_format="wav",
        )
        for label, (first, second) in CASES.items()
    }


async def synthesize(api_key: str, output: Path) -> None:
    storage = LocalObjectStorageProvider(output / "assets")
    provider = DoubaoPodcastSpeechProvider(
        DoubaoPodcastWebSocketTransport(
            api_key, os.getenv("DOUBAO_PODCAST_RESOURCE_ID", DOUBAO_PODCAST_RESOURCE_ID)
        ),
        storage,
    )
    for label, request in requests().items():
        asset = await provider.synthesize_dialogue(request)
        stored = await storage.get(asset.asset_id)
        if stored is None:
            raise RuntimeError("probe audio was not stored")
        path = output / f"{label}.wav"
        path.write_bytes(stored.content)
        print(json.dumps({"case": label, "path": str(path), "seconds": asset.duration}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="make three paid TTS calls")
    parser.add_argument("--output", type=Path, default=Path("/tmp/wavecast-podcast-case-probe"))
    args = parser.parse_args()
    if not args.run_live:
        for label, request in requests().items():
            print(json.dumps({"case": label, "texts": [t.text for t in request.turns]}, ensure_ascii=False))
        print("Preview only; pass --run-live to synthesize three samples.")
        return

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.getenv("DOUBAO_PODCAST_API_KEY")
    if not api_key:
        raise SystemExit("Configure DOUBAO_PODCAST_API_KEY; no provider calls were made.")
    try:
        asyncio.run(synthesize(api_key, args.output.expanduser().resolve()))
    except ProviderError as error:
        raise SystemExit(f"Podcast probe failed: {type(error).__name__}") from None


if __name__ == "__main__":
    main()
