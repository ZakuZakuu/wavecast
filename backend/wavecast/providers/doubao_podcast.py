"""Doubao fixed-script two-voice speech for a researched passage.

Two layers.  :class:`DoubaoPodcastSpeechProvider` owns what the application needs from a vendor:
the cache key and storage of the audio, a local WAV container around the vendor's PCM, the
response checks, the error mapping, and **exactly one final usage event per attempt** - whether
the attempt succeeded, the service failed, the response did not pass the checks, storing the
audio failed, or the caller cancelled.  :class:`DoubaoPodcastWebSocketTransport` owns the wire:
the binary WebSocket exchange that the successful 2026-10-14 experiment used (see
``doubao_frames`` and ADR 0027).

Verified, and therefore all that is supported: the ``/api/v3/sami/podcasttts`` endpoint with
``X-Api-Key`` and the ``volc.service_type.10050`` resource, ``action = 3`` (the given script is
voiced as written), 24 kHz mono 16-bit PCM, speech rate 0, the fixed voices of the request, one
session per passage.  Not verified and not offered: other rates, server-side MP3/WAV, native
timestamps (per-line times are derived from the PCM byte counts), any retry or reconnect.

A transport must never return audio that differs from the script; if a line is not the one that
was asked for, or the dialogue is incomplete, it raises and returns nothing.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import time
import uuid
import wave
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from wavecast.providers import doubao_frames as frames
from wavecast.providers.contracts import AudioAsset, AudioAssetType, ObjectStorageProvider
from wavecast.providers.dialogue_speech import build_dialogue_cache_key
from wavecast.providers.doubao_voices import DOUBAO_PROVIDER_NAME
from wavecast.providers.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    ProviderIncompleteResponseError,
    ProviderInvalidResponseError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from wavecast.providers.speech import SpeechRequest
from wavecast.providers.usage import UsageEvent, UsageLedger

DOUBAO_PODCAST_MODEL = "doubao-podcast"
DOUBAO_PODCAST_PROTOCOL = "doubao-podcast-fixed-script-pcm24k-v1"
DOUBAO_PODCAST_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"
DOUBAO_PODCAST_RESOURCE_ID = "volc.service_type.10050"
SAMPLE_RATE = 24000
BYTES_PER_SECOND = SAMPLE_RATE * 2
# The only speech rate that has been run against the service (Doubao's own scale).
VERIFIED_SPEECH_RATE = 0
SUPPORTED_AUDIO_FORMATS = ("wav",)
DEFAULT_AUDIO_FORMAT = "wav"
# Local guard against a runaway response; not a limit of the service.
DEFAULT_MAX_AUDIO_SECONDS = 600.0
_USAGE_FIELDS = ("input_text_tokens", "output_audio_tokens")


@dataclass(frozen=True)
class ScriptLine:
    speaker: str
    voice_id: str
    text: str


@dataclass(frozen=True)
class PodcastScript:
    lines: tuple[ScriptLine, ...]
    # Distinct voice ids in host order (A first); sent as the session's speaker list.
    voices: tuple[str, ...]
    speech_rate: int
    audio_format: str


@dataclass(frozen=True)
class PodcastAudio:
    """What a completed session produced: PCM, and how many bytes belong to each line."""

    pcm: bytes
    sample_rate: int
    line_byte_lengths: tuple[int, ...]


@dataclass
class PodcastAttempt:
    """What one attempt learned, filled in by the transport while it runs.

    The adapter reads it when the attempt ends, however it ends, so usage the service already
    reported is not lost to a failure later on the application's side.
    """

    request_id: str | None = None
    usage_reports: list[dict[str, int]] = field(default_factory=list)
    rounds_completed: int = 0
    audio_bytes: int = 0
    session_finished: bool = False

    def add_usage(self, raw: object) -> None:
        """Keep the numeric token counts of one usage report; nothing else is retained."""

        if not isinstance(raw, Mapping):
            return
        report: dict[str, int] = {}
        for name in _USAGE_FIELDS:
            value = raw.get(name)
            if isinstance(value, (int, float)) and _is_count(value):
                report[name] = int(value)
        if report:
            self.usage_reports.append(report)

    def total(self, name: str) -> int | None:
        """Sum of a field over the reports that carried it; ``None`` when none did (not zero)."""

        values = [report[name] for report in self.usage_reports if name in report]
        return sum(values) if values else None

    def usage_status(self) -> str:
        """``complete``: the session finished and both counts arrived; ``partial``: some did."""

        known = [self.total(name) for name in _USAGE_FIELDS]
        if all(value is None for value in known):
            return "unknown"
        return "complete" if self.session_finished and None not in known else "partial"


def _is_count(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value >= 0 and float(value).is_integer()


class PodcastTransport(Protocol):
    async def synthesize(self, script: PodcastScript, attempt: PodcastAttempt) -> PodcastAudio: ...


class DoubaoPodcastSpeechProvider:
    provider_name = DOUBAO_PROVIDER_NAME
    model = DOUBAO_PODCAST_MODEL
    protocol_version = DOUBAO_PODCAST_PROTOCOL

    def __init__(
        self,
        transport: PodcastTransport,
        storage: ObjectStorageProvider,
        *,
        ledger: UsageLedger | None = None,
    ) -> None:
        self._transport = transport
        self._storage = storage
        self._ledger = ledger or UsageLedger()

    def cache_key(self, request: SpeechRequest) -> str:
        return build_dialogue_cache_key(
            provider=self.provider_name,
            model=self.model,
            request=request,
            protocol_version=self.protocol_version,
            extension=self._format(request),
        )

    async def synthesize_dialogue(self, request: SpeechRequest) -> AudioAsset:
        script = self._script(request)  # a request that cannot be made is not an attempt
        key = self.cache_key(request)
        attempt = PodcastAttempt()
        started = time.monotonic()
        stage = "transport"
        outcome = "error"
        audio_seconds: float | None = None
        try:
            result = await self._transport.synthesize(script, attempt)
            stage = "validate"
            wav_bytes, audio_seconds, timings = self._validated(result, script)
            stage = "store"
            duration = max(1, math.ceil(audio_seconds))
            url = await self._storage.put(
                key,
                wav_bytes,
                "audio/wav",
                metadata={
                    "duration_seconds": duration,
                    "provider": self.provider_name,
                    "turn_timings": timings,
                    "voices": [role.model_dump(mode="json") for role in request.roles],
                },
            )
            outcome = "ok"
            return AudioAsset(
                asset_id=key,
                asset_type=AudioAssetType.NARRATION,
                provider=self.provider_name,
                playback_url=url,
                duration=duration,
                metadata={"cache_key": key, "turn_timings": timings, "cache_hit": False},
            )
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except ProviderError as error:
            outcome = type(error).__name__
            raise
        except Exception as error:  # noqa: BLE001 - the vendor boundary: map, never leak
            outcome = "storage_error" if stage == "store" else "transport_error"
            raise ProviderInvalidResponseError("doubao podcast synthesis failed") from error
        finally:
            self._record(started, script, attempt, outcome, stage, audio_seconds)

    @staticmethod
    def _format(request: SpeechRequest) -> str:
        audio_format = request.audio_format or DEFAULT_AUDIO_FORMAT
        if audio_format not in SUPPORTED_AUDIO_FORMATS:
            raise ProviderConfigurationError(
                f"doubao podcast audio format {audio_format!r} is not supported "
                f"(verified: {', '.join(SUPPORTED_AUDIO_FORMATS)})"
            )
        return audio_format

    def _script(self, request: SpeechRequest) -> PodcastScript:
        if not request.is_dialogue:
            raise ProviderConfigurationError("doubao podcast speech needs a dialogue request")
        speed = 0.0 if request.speed is None else request.speed
        if speed != VERIFIED_SPEECH_RATE:
            raise ProviderConfigurationError(
                f"doubao speech rate {speed:g} has not been verified (only {VERIFIED_SPEECH_RATE})"
            )
        voices = {role.speaker: role.voice_id for role in request.roles}
        ordered = tuple(
            dict.fromkeys(voice for _, voice in sorted(voices.items(), key=lambda item: item[0].value))
        )
        return PodcastScript(
            lines=tuple(
                ScriptLine(turn.speaker.value, voices[turn.speaker], turn.text)
                for turn in request.turns
            ),
            voices=ordered,
            speech_rate=VERIFIED_SPEECH_RATE,
            audio_format=self._format(request),
        )

    @staticmethod
    def _validated(
        result: PodcastAudio, script: PodcastScript
    ) -> tuple[bytes, float, list[dict[str, object]]]:
        pcm = result.pcm
        if not pcm or len(pcm) % 2:
            raise ProviderInvalidResponseError("doubao podcast returned no usable audio")
        if result.sample_rate != SAMPLE_RATE:
            raise ProviderInvalidResponseError("doubao podcast returned a different sample rate")
        lengths = result.line_byte_lengths
        if (
            len(lengths) != len(script.lines)
            or any(length <= 0 or length % 2 for length in lengths)
            or sum(lengths) != len(pcm)
        ):
            raise ProviderInvalidResponseError("doubao podcast audio does not match the script")
        timings: list[dict[str, object]] = []
        cursor = 0
        for line, length in zip(script.lines, lengths, strict=True):
            start = cursor / BYTES_PER_SECOND
            cursor += length
            timings.append(
                {"speaker": line.speaker, "start": round(start, 3), "end": round(cursor / BYTES_PER_SECOND, 3)}
            )
        return _wav(pcm), len(pcm) / BYTES_PER_SECOND, timings

    def _record(
        self,
        started: float,
        script: PodcastScript,
        attempt: PodcastAttempt,
        outcome: str,
        stage: str,
        audio_seconds: float | None,
    ) -> None:
        """The one final event of this attempt.  Counts and outcomes only: no text, no URLs."""

        metadata: dict[str, Any] = {
            "outcome": outcome,
            "model": self.model,
            "protocol": self.protocol_version,
            "turns": len(script.lines),
            "rounds_completed": attempt.rounds_completed,
            "usage_status": attempt.usage_status(),
            # The service's own counts; ``None`` is unknown, a reported zero stays zero.
            "input_text_tokens": attempt.total("input_text_tokens"),
            "output_audio_tokens": attempt.total("output_audio_tokens"),
            # A local count of what was sent - not what was billed.
            "sent_characters": sum(len(line.text) for line in script.lines),
        }
        metadata.update(_price(attempt))
        if outcome != "ok":
            metadata["failed_stage"] = stage
        if audio_seconds is not None:
            metadata["audio_seconds"] = round(audio_seconds, 3)
        self._ledger.record(
            UsageEvent(
                provider=self.provider_name,
                operation="dialogue_speech",
                request_id=attempt.request_id,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                metadata=metadata,
            )
        )


# Published rates for the podcast model (CNY per million tokens), as the user gave them on
# 2026-10-15.  Bump the version when they change.
PRICE_VERSION = "doubao-podcast-2026-10-15"
INPUT_TEXT_CNY_PER_MILLION = 120.0
OUTPUT_AUDIO_CNY_PER_MILLION = 100.0


def _price(attempt: PodcastAttempt) -> dict[str, Any]:
    """The cost of an attempt from the counts the service reported - never from characters.

    A reported zero stays zero (receipts have carried 0 input text tokens so far).  Unless the
    session finished and both counts arrived the cost is unknown (``None``), not a smaller
    number: the service may have billed more than it told us.
    """

    input_text = attempt.total("input_text_tokens")
    output_audio = attempt.total("output_audio_tokens")
    if attempt.usage_status() != "complete" or input_text is None or output_audio is None:
        cost = None
        basis = "usage_incomplete"
    else:
        cost = round(
            (input_text * INPUT_TEXT_CNY_PER_MILLION + output_audio * OUTPUT_AUDIO_CNY_PER_MILLION)
            / 1_000_000,
            8,
        )
        basis = "reported_token_counts"
    return {
        "estimated_cost_cny": cost,
        "estimated_cost_cny_low": cost,
        "estimated_cost_cny_high": cost,
        "cost_basis": basis,
        "price_version": PRICE_VERSION,
    }


def _wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm)
    return buffer.getvalue()


# --- the wire -------------------------------------------------------------------------------


class _Connection(Protocol):
    async def send(self, data: bytes) -> None: ...

    async def recv(self) -> bytes | str: ...

    async def close(self) -> None: ...


Connect = Callable[[str, Mapping[str, str]], Awaitable[_Connection]]


async def _connect_websockets(url: str, headers: Mapping[str, str]) -> _Connection:
    try:
        from websockets.asyncio.client import connect
    except ImportError as error:  # pragma: no cover - uvicorn[standard] brings websockets
        raise ProviderConfigurationError("the websockets package is required for Doubao speech") from error
    connection: _Connection = await connect(
        url, additional_headers=dict(headers), open_timeout=30.0, max_size=4_000_000
    )
    return connection


class DoubaoPodcastWebSocketTransport:
    """One passage = one connection = one session.  No retry, no reconnect, no resend."""

    def __init__(
        self,
        api_key: str,
        resource_id: str = DOUBAO_PODCAST_RESOURCE_ID,
        *,
        endpoint: str = DOUBAO_PODCAST_ENDPOINT,
        connect: Connect | None = None,
        receive_timeout: float = 60.0,
        total_timeout: float = 600.0,
        max_audio_seconds: float = DEFAULT_MAX_AUDIO_SECONDS,
    ) -> None:
        if not api_key:
            raise ProviderConfigurationError("doubao podcast speech requires DOUBAO_PODCAST_API_KEY")
        self._api_key = api_key
        self._resource_id = resource_id
        self._endpoint = endpoint
        self._connect = connect or _connect_websockets
        self._receive_timeout = receive_timeout
        self._total_timeout = total_timeout
        self._max_audio_bytes = int(max_audio_seconds * BYTES_PER_SECOND)

    def __repr__(self) -> str:  # never show the key
        return f"DoubaoPodcastWebSocketTransport(resource_id={self._resource_id!r})"

    async def synthesize(self, script: PodcastScript, attempt: PodcastAttempt) -> PodcastAudio:
        request_id = str(uuid.uuid4())
        attempt.request_id = request_id
        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": self._resource_id,
            "X-Api-Request-Id": request_id,
        }
        try:
            async with asyncio.timeout(self._total_timeout):
                return await self._exchange(script, attempt, headers)
        except TimeoutError as error:
            raise ProviderTimeoutError("doubao podcast synthesis timed out") from error

    async def _exchange(
        self, script: PodcastScript, attempt: PodcastAttempt, headers: Mapping[str, str]
    ) -> PodcastAudio:
        connection = await self._open(headers)
        try:
            session = str(uuid.uuid4())
            await self._send(connection, frames.start_connection())
            await self._expect(connection, frames.Event.CONNECTION_STARTED, attempt)
            await self._send(connection, frames.start_session(session, _session_payload(script)))
            await self._expect(connection, frames.Event.SESSION_STARTED, attempt)
            await self._send(connection, frames.finish_session(session))
            audio = await self._collect(connection, script, attempt)
            # The dialogue is complete and billed; closing politely must not discard it.
            try:
                await self._send(connection, frames.finish_connection())
                await self._expect(connection, frames.Event.CONNECTION_FINISHED, attempt)
            except (ProviderError, OSError):
                pass
            return audio
        finally:
            await asyncio.shield(_close_quietly(connection))

    async def _open(self, headers: Mapping[str, str]) -> _Connection:
        try:
            return await self._connect(self._endpoint, headers)
        except ProviderError:
            raise
        except TimeoutError as error:
            raise ProviderTimeoutError("doubao podcast connection timed out") from error
        except Exception as error:  # noqa: BLE001
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status == 401:
                raise ProviderAuthenticationError("doubao podcast rejected the credentials") from error
            if status == 403:
                raise ProviderPermissionError("doubao podcast refused the request") from error
            if status == 429:
                raise ProviderRateLimitError("doubao podcast is rate limited") from error
            raise ProviderUnavailableError("doubao podcast could not be reached") from error

    async def _send(self, connection: _Connection, data: bytes) -> None:
        try:
            await connection.send(data)
        except Exception as error:  # noqa: BLE001
            raise ProviderUnavailableError("doubao podcast connection failed while sending") from error

    async def _receive(self, connection: _Connection) -> frames.Frame:
        try:
            data = await asyncio.wait_for(connection.recv(), timeout=self._receive_timeout)
        except TimeoutError as error:
            raise ProviderTimeoutError("doubao podcast stopped answering") from error
        except Exception as error:  # noqa: BLE001
            raise ProviderUnavailableError("doubao podcast connection closed unexpectedly") from error
        if not isinstance(data, bytes):
            raise ProviderInvalidResponseError("doubao podcast sent a non-binary message")
        frame = frames.parse_server_frame(data)
        if frame.type is frames.MsgType.ERROR:
            # The numeric code is all that is kept; the body of an error is not logged or raised.
            raise ProviderRequestError(f"doubao podcast error code {frame.error_code}")
        if frame.event in (
            frames.Event.CONNECTION_FAILED,
            frames.Event.SESSION_FAILED,
            frames.Event.SESSION_CANCELED,
        ):
            raise ProviderUnavailableError(f"doubao podcast reported event {int(frame.event)}")
        return frame

    async def _expect(
        self, connection: _Connection, event: frames.Event, attempt: PodcastAttempt
    ) -> None:
        while True:
            frame = await self._receive(connection)
            if frame.event == frames.Event.USAGE_RESPONSE:
                attempt.add_usage(_json_object(frame.payload).get("usage"))
                continue
            if frame.event != event:
                raise ProviderInvalidResponseError(f"doubao podcast sent unexpected event {_name(frame.event)}")
            return

    async def _collect(
        self, connection: _Connection, script: PodcastScript, attempt: PodcastAttempt
    ) -> PodcastAudio:
        rounds: list[bytes] = []
        current: bytearray | None = None
        while True:
            frame = await self._receive(connection)
            event = frame.event
            if event == frames.Event.PODCAST_ROUND_START:
                info = _json_object(frame.payload)
                index = len(rounds)
                if current is not None:
                    raise ProviderInvalidResponseError("doubao podcast started a round inside a round")
                if (
                    index >= len(script.lines)
                    or info.get("speaker") != script.lines[index].voice_id
                    or info.get("text") != script.lines[index].text
                ):
                    raise ProviderInvalidResponseError("doubao podcast changed the dialogue")
                current = bytearray()
            elif event == frames.Event.PODCAST_ROUND_RESPONSE:
                if current is None:
                    raise ProviderInvalidResponseError("doubao podcast sent audio outside a round")
                current.extend(frame.payload)
                attempt.audio_bytes += len(frame.payload)
                if attempt.audio_bytes > self._max_audio_bytes:
                    raise ProviderInvalidResponseError("doubao podcast audio exceeds the local guard")
            elif event == frames.Event.PODCAST_ROUND_END:
                info = _json_object(frame.payload)
                if current is None or info.get("is_error"):
                    raise ProviderInvalidResponseError("doubao podcast round failed")
                pcm = bytes(current)
                if not pcm or len(pcm) % 2:
                    raise ProviderInvalidResponseError("doubao podcast round has no usable audio")
                reported = info.get("audio_duration")
                seconds = len(pcm) / BYTES_PER_SECOND
                if (
                    isinstance(reported, (int, float))
                    and not isinstance(reported, bool)
                    and abs(reported - seconds) > max(1.0, seconds * 0.05)
                ):
                    raise ProviderInvalidResponseError("doubao podcast round length disagrees with its audio")
                rounds.append(pcm)
                attempt.rounds_completed = len(rounds)
                current = None
            elif event == frames.Event.USAGE_RESPONSE:
                attempt.add_usage(_json_object(frame.payload).get("usage"))
            elif event == frames.Event.PODCAST_END:
                continue
            elif event == frames.Event.SESSION_FINISHED:
                break
            else:
                raise ProviderInvalidResponseError(f"doubao podcast sent unexpected event {_name(event)}")
        if current is not None or len(rounds) != len(script.lines):
            raise ProviderIncompleteResponseError("doubao podcast ended before the dialogue was complete")
        attempt.session_finished = True
        return PodcastAudio(
            pcm=b"".join(rounds),
            sample_rate=SAMPLE_RATE,
            line_byte_lengths=tuple(len(chunk) for chunk in rounds),
        )


def _session_payload(script: PodcastScript) -> bytes:
    return json.dumps(
        {
            "action": 3,
            "nlp_texts": [{"speaker": line.voice_id, "text": line.text} for line in script.lines],
            "use_head_music": False,
            "use_tail_music": False,
            "input_info": {"return_audio_url": False},
            "speaker_info": {"random_order": False, "speakers": list(script.voices)},
            "audio_config": {
                "format": "pcm",
                "sample_rate": SAMPLE_RATE,
                "speech_rate": script.speech_rate,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _json_object(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload) if payload else {}
    except ValueError as error:
        raise ProviderInvalidResponseError("doubao podcast sent an unreadable message") from error
    if not isinstance(value, dict):
        raise ProviderInvalidResponseError("doubao podcast sent an unexpected message")
    return value


def _name(event: object) -> str:
    return str(int(event)) if isinstance(event, int) else "none"


async def _close_quietly(connection: _Connection) -> None:
    try:
        await connection.close()
    except Exception:  # noqa: BLE001, S110 - closing must not mask the real outcome
        pass


__all__ = [
    "DEFAULT_AUDIO_FORMAT",
    "DOUBAO_PODCAST_ENDPOINT",
    "DOUBAO_PODCAST_MODEL",
    "DOUBAO_PODCAST_PROTOCOL",
    "DOUBAO_PODCAST_RESOURCE_ID",
    "DoubaoPodcastSpeechProvider",
    "DoubaoPodcastWebSocketTransport",
    "PodcastAttempt",
    "PodcastAudio",
    "PodcastScript",
    "PodcastTransport",
    "ScriptLine",
]
