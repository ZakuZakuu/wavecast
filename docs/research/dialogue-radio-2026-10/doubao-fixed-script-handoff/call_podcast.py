"""Historical one-shot reference client (not production code). Dry-run by default; never retries.

Protocol helpers come from bytedance/agentkit-samples (Apache-2.0).
Only numeric usage and completed audio are retained from provider responses.
"""
import argparse
import asyncio
import hashlib
import getpass
import json
import os
import time
import uuid
import wave
from pathlib import Path

import websockets
from protocols import EventType, Message, MsgType, finish_connection, finish_session, start_connection, start_session

ROOT = Path(__file__).parent
ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"
RATE = 24000
MAX_AUDIO_SECONDS = 300


def validate(payload):
    turns = payload["nlp_texts"]
    if payload["action"] != 3 or not 1 <= len(turns) <= 30:
        raise ValueError("fixed dialogue required")
    if any(not 0 < len(t["text"]) <= 300 for t in turns):
        raise ValueError("turn length outside budget")
    if sum(len(t["text"]) for t in turns) > 1500:
        raise ValueError("demo text exceeds budget")
    if payload["audio_config"] != {"format": "pcm", "sample_rate": RATE, "speech_rate": 0}:
        raise ValueError("unexpected audio format")
    return turns


def write_wav(path, pcm):
    if not pcm or len(pcm) % 2:
        raise ValueError("incomplete PCM audio")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(pcm)


async def receive(ws):
    data = await asyncio.wait_for(ws.recv(), timeout=60)
    if not isinstance(data, bytes):
        raise ValueError("unexpected message type")
    # Bypass the sample's receiver, which logs full payloads.
    msg = Message.from_bytes(data)
    if msg.type == MsgType.Error:
        raise RuntimeError(f"provider_error_code_{msg.error_code}")
    return msg


def usage_from_message(msg):
    u = json.loads(msg.payload).get("usage", {})
    return {k:v for k,v in u.items() if k in {"input_text_tokens", "output_audio_tokens"} and isinstance(v,(int,float))}


async def expect(ws, event, usage=None):
    while True:
        msg = await receive(ws)
        if msg.event == EventType.UsageResponse and usage is not None:
            usage.append(usage_from_message(msg))
            continue
        if msg.event != event:
            raise RuntimeError(f"unexpected_event_{int(msg.event)}")
        return


async def generate(payload):
    turns = validate(payload)
    key = os.environ.get("DOUBAO_PODCAST_API_KEY")
    if not key:
        raise RuntimeError("missing_demo_key")
    # A failed attempt also creates this marker. Restarting never silently retries.
    marker = ROOT / "attempt.json"
    if marker.exists():
        raise RuntimeError("attempt_already_exists_no_automatic_retry")
    session = str(uuid.uuid4())
    marker.write_text(json.dumps({"task_id": session, "started_at_unix": time.time()}))
    out = ROOT / "narration"
    out.mkdir(exist_ok=True)
    headers = {"X-Api-Key": key, "X-Api-Resource-Id": "volc.service_type.10050", "X-Api-Request-Id": str(uuid.uuid4())}
    usage = []
    completed = []
    total_bytes = 0
    current = None
    started = time.monotonic()
    def checkpoint(status):
        result = {"status":status,"task_id":session,"rounds":completed,"audio_seconds":total_bytes/(RATE*2),"usage_events":usage,"elapsed_seconds":time.monotonic()-started,"retries":0}
        (ROOT / "generation-summary.json").write_text(json.dumps(result,indent=2))
        return result
    async with asyncio.timeout(600):
        async with websockets.connect(ENDPOINT, additional_headers=headers, open_timeout=30, max_size=4_000_000) as ws:
            await start_connection(ws)
            await expect(ws, EventType.ConnectionStarted, usage)
            await start_session(ws, json.dumps(payload, ensure_ascii=False).encode(), session)
            await expect(ws, EventType.SessionStarted, usage)
            await finish_session(ws, session)
            while True:
                msg = await receive(ws)
                if msg.event == EventType.PodcastRoundStart:
                    if current is not None:
                        raise RuntimeError("overlapping_rounds")
                    info = json.loads(msg.payload)
                    index = len(completed)
                    if index >= len(turns) or info.get("speaker") != turns[index]["speaker"] or info.get("text") != turns[index]["text"]:
                        raise RuntimeError("dialogue_round_alignment_changed")
                    current = {"index": index, "round_id": info.get("round_id"), "pcm": bytearray()}
                elif msg.event == EventType.PodcastRoundResponse:
                    if current is None:
                        raise RuntimeError("audio_without_round")
                    current["pcm"].extend(msg.payload)
                    total_bytes += len(msg.payload)
                    if total_bytes > RATE * 2 * MAX_AUDIO_SECONDS:
                        raise RuntimeError("audio_budget_exceeded")
                elif msg.event == EventType.PodcastRoundEnd:
                    info = json.loads(msg.payload)
                    if info.get("is_error") or current is None:
                        raise RuntimeError("round_generation_failed")
                    pcm = bytes(current.pop("pcm"))
                    duration = len(pcm) / (RATE * 2)
                    reported = info.get("audio_duration")
                    if isinstance(reported, (int, float)) and abs(reported-duration) > max(1, duration * .05):
                        raise RuntimeError("pcm_duration_needs_review")
                    filename = f"turn-{current['index']:02}.wav"
                    write_wav(out / filename, pcm)
                    completed.append({**current, "file": filename, "duration_seconds": duration, "sha256": hashlib.sha256(pcm).hexdigest()})
                    current = None
                    checkpoint("generating")
                    print(json.dumps({"completed_turns": len(completed), "audio_seconds": total_bytes/(RATE*2)}), flush=True)
                elif msg.event == EventType.UsageResponse:
                    usage.append(usage_from_message(msg))
                    checkpoint("generating")
                elif msg.event == EventType.SessionFinished:
                    break
            if current is not None or len(completed) != len(turns):
                raise RuntimeError("incomplete_dialogue")
            await finish_connection(ws)
            await expect(ws, EventType.ConnectionFinished, usage)
    result = checkpoint("completed")
    print(json.dumps({"status": "completed", "audio_seconds": result["audio_seconds"], "usage_events": usage}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--prompt-key", action="store_true")
    args = parser.parse_args()
    payload = json.loads((ROOT / "dialogue.json").read_text())
    turns = validate(payload)
    if not args.live:
        print(json.dumps({"mode": "dry_run", "turns": len(turns), "characters": sum(len(t["text"]) for t in turns), "audio_limit_seconds": MAX_AUDIO_SECONDS, "network_calls": 0}))
    else:
        if args.prompt_key:
            os.environ["DOUBAO_PODCAST_API_KEY"] = getpass.getpass("Temporary demo key: ")
        try:
            asyncio.run(generate(payload))
        except Exception as error:
            # Avoid server errors/headers leaking secrets or signed URLs.
            diagnostic = {"status": "failed", "error_type": type(error).__name__, "automatic_retry": False}
            response = getattr(error, "response", None)
            if response is not None:
                diagnostic["http_status"] = getattr(response, "status_code", None)
                # Preserve safe request identifiers and numeric error codes only.
                headers = getattr(response, "headers", None)
                if headers is not None:
                    for header in ("x-tt-logid", "x-tt-error-code"):
                        values = headers.get_all(header)
                        if values:
                            diagnostic[header] = values
                try:
                    body = json.loads(bytes(response.body))
                    for field in ("code", "error_code", "status_code"):
                        if isinstance(body.get(field), (int, float)):
                            diagnostic[field] = body[field]
                except (ValueError, TypeError, AttributeError):
                    pass
            if isinstance(error, RuntimeError) and str(error).replace("_", "").isalnum():
                diagnostic["reason"] = str(error)
            print(json.dumps(diagnostic))
            raise SystemExit(1)
        finally:
            os.environ.pop("DOUBAO_PODCAST_API_KEY", None)
