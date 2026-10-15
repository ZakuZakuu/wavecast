"""The Doubao dialogue adapter and its WebSocket transport, driven by fakes (no network, no key).

The frames the fake server sends are built with the same layout the verified 2026-10-14 run
used (``tests`` build them with ``doubao_frames.build_frame``).  What this does not show: the
real service's behaviour today; one minimal live attempt is arranged separately.
"""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Mapping
from typing import Any

import pytest
from wavecast.materialization import NarrationMaterializer
from wavecast.models.dialogue import DialogueBlock, DialoguePurpose, DialogueSpeaker, DialogueTurn
from wavecast.models.episode import NarrationSegment, SegmentState
from wavecast.providers import doubao_frames as frames
from wavecast.providers.doubao_podcast import (
    BYTES_PER_SECOND,
    DOUBAO_PODCAST_PROTOCOL,
    DoubaoPodcastSpeechProvider,
    DoubaoPodcastWebSocketTransport,
    PodcastAttempt,
    PodcastAudio,
    PodcastScript,
)
from wavecast.providers.doubao_voices import SPEECH_RATE_B, VOICE_COMBINATION_B
from wavecast.providers.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderIncompleteResponseError,
    ProviderInvalidResponseError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from wavecast.providers.fakes import MockTTSProvider
from wavecast.providers.speech import SpeechRequest
from wavecast.providers.usage import UsageLedger, safe_usage_event, usage_diagnostics
from wavecast.storage import LocalObjectStorageProvider

A_VOICE, B_VOICE = (role.voice_id for role in VOICE_COMBINATION_B)
LINE_A, LINE_B = "刚听完这首歌。", "我也这么想。"


def _block(text_b: str = LINE_B) -> DialogueBlock:
    return DialogueBlock(
        block_id="b1",
        slot_id="s1",
        story_id="st-1",
        purpose=DialoguePurpose.STORY,
        turns=[
            DialogueTurn(speaker=DialogueSpeaker.A, text=LINE_A, tts_text=None, fact_refs=[]),
            DialogueTurn(speaker=DialogueSpeaker.B, text=text_b, tts_text=None, fact_refs=[]),
        ],
        duration_seconds=10,
    )


def _request(block: DialogueBlock | None = None, **changes: object) -> SpeechRequest:
    base: dict[str, object] = dict(speed=float(SPEECH_RATE_B), audio_format="wav")
    return SpeechRequest.dialogue(block or _block(), list(VOICE_COMBINATION_B), **{**base, **changes})  # type: ignore[arg-type]


def _pcm(seconds: float) -> bytes:
    return b"\x01\x00" * int(seconds * BYTES_PER_SECOND / 2)


# --- the adapter, over a fake transport ------------------------------------------------------


class FakeTransport:
    """Fills the attempt as a transport would, then returns audio or fails."""

    def __init__(
        self,
        result: PodcastAudio | BaseException | None = None,
        *,
        usage: list[dict[str, Any]] | None = None,
        finished: bool = True,
    ) -> None:
        self.result = result if result is not None else PodcastAudio(
            pcm=_pcm(3.0) + _pcm(4.2), sample_rate=24000,
            line_byte_lengths=(len(_pcm(3.0)), len(_pcm(4.2))),
        )  # fmt: skip
        self.usage = usage if usage is not None else [{"input_text_tokens": 0, "output_audio_tokens": 403}]
        self.finished = finished
        self.scripts: list[PodcastScript] = []

    async def synthesize(self, script: PodcastScript, attempt: PodcastAttempt) -> PodcastAudio:
        self.scripts.append(script)
        attempt.request_id = "req-1"
        attempt.rounds_completed = 1
        for report in self.usage:
            attempt.add_usage(report)
        attempt.session_finished = self.finished
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class FailingStorage(LocalObjectStorageProvider):
    def __init__(self, root: Any, failure: BaseException) -> None:
        super().__init__(root)
        self.failure = failure

    async def put(self, *args: Any, **kwargs: Any) -> str:
        raise self.failure


def _provider(tmp_path, transport: FakeTransport | None = None, storage: Any = None):  # type: ignore[no-untyped-def]
    storage = storage or LocalObjectStorageProvider(tmp_path / "audio")
    ledger = UsageLedger()
    transport = transport or FakeTransport()
    return DoubaoPodcastSpeechProvider(transport, storage, ledger=ledger), transport, storage, ledger


def test_the_script_is_sent_exactly_with_each_host_s_own_voice(tmp_path) -> None:
    provider, transport, *_ = _provider(tmp_path)

    asset = asyncio.run(provider.synthesize_dialogue(_request()))

    (script,) = transport.scripts
    assert [(line.speaker, line.voice_id, line.text) for line in script.lines] == [
        ("A", A_VOICE, LINE_A),
        ("B", B_VOICE, LINE_B),
    ]
    assert script.voices == (A_VOICE, B_VOICE) and script.speech_rate == 0
    assert asset.duration == 8  # 7.2 s rounded up: the timeline plans with whole seconds
    assert asset.asset_id.startswith("dialogue-") and asset.asset_id.endswith(".wav")
    assert asset.metadata["turn_timings"] == [
        {"speaker": "A", "start": 0.0, "end": 3.0},
        {"speaker": "B", "start": 3.0, "end": 7.2},
    ]


def test_the_pcm_is_wrapped_locally_as_a_wav_and_stored(tmp_path) -> None:
    import io
    import wave

    provider, _, storage, _ = _provider(tmp_path)
    asset = asyncio.run(provider.synthesize_dialogue(_request()))

    stored = asyncio.run(storage.get(asset.asset_id))

    assert stored is not None and stored.metadata["duration_seconds"] == 8
    with wave.open(io.BytesIO(stored.content)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert wav.getnframes() / 24000 == pytest.approx(7.2)


def test_the_cache_key_follows_everything_that_changes_what_is_heard(tmp_path) -> None:
    provider, *_ = _provider(tmp_path)
    base = provider.cache_key(_request())

    assert provider.cache_key(_request()) == base and base.endswith(".wav")
    assert provider.cache_key(_request(_block("换一句话。"))) != base
    swapped = SpeechRequest.dialogue(
        _block(),
        [VOICE_COMBINATION_B[0], VOICE_COMBINATION_B[1].model_copy(update={"voice_id": "another_voice"})],
        speed=0.0,
        audio_format="wav",
    )
    assert provider.cache_key(swapped) != base


def test_a_success_leaves_exactly_one_final_event_with_the_known_counts(tmp_path) -> None:
    provider, _, _, ledger = _provider(tmp_path)
    asyncio.run(provider.synthesize_dialogue(_request()))

    (event,) = ledger.events
    meta = event.metadata
    assert (event.provider, event.operation, event.request_id) == ("doubao_podcast", "dialogue_speech", "req-1")
    assert meta["outcome"] == "ok" and meta["protocol"] == DOUBAO_PODCAST_PROTOCOL
    assert (meta["input_text_tokens"], meta["output_audio_tokens"]) == (0, 403)  # a reported zero stays zero
    assert meta["usage_status"] == "complete" and meta["audio_seconds"] == 7.2
    assert meta["sent_characters"] == len(LINE_A + LINE_B) and meta["cost_basis"] == "unpriced"
    assert event.estimated_cost_usd is None and event.actual_cost_usd is None  # unknown, not zero
    assert event.usage_characters is None  # nothing was billed in characters
    assert LINE_A not in str(event.model_dump())


@pytest.mark.parametrize(
    ("make_storage", "outcome", "stage"),
    [
        (lambda root: FailingStorage(root, OSError("disk full")), "storage_error", "store"),
        (lambda root: FailingStorage(root, asyncio.CancelledError()), "cancelled", "store"),
    ],
    ids=["upload-fails", "upload-cancelled"],
)
def test_failing_to_store_still_keeps_what_the_service_reported(tmp_path, make_storage, outcome, stage) -> None:  # type: ignore[no-untyped-def]
    provider, transport, _, ledger = _provider(tmp_path, storage=make_storage(tmp_path / "audio"))
    expected = asyncio.CancelledError if outcome == "cancelled" else ProviderInvalidResponseError

    with pytest.raises(expected):
        asyncio.run(provider.synthesize_dialogue(_request()))

    assert len(transport.scripts) == 1  # no retry
    (event,) = ledger.events
    assert event.metadata["outcome"] == outcome and event.metadata["failed_stage"] == stage
    assert event.metadata["output_audio_tokens"] == 403 and event.metadata["usage_status"] == "complete"


@pytest.mark.parametrize(
    "bad",
    [
        PodcastAudio(pcm=b"", sample_rate=24000, line_byte_lengths=(0, 0)),
        PodcastAudio(pcm=b"\x01", sample_rate=24000, line_byte_lengths=(1, 0)),
        PodcastAudio(pcm=_pcm(1), sample_rate=16000, line_byte_lengths=(len(_pcm(1)) // 2,) * 2),
        PodcastAudio(pcm=_pcm(2), sample_rate=24000, line_byte_lengths=(len(_pcm(2)),)),
        PodcastAudio(pcm=_pcm(2), sample_rate=24000, line_byte_lengths=(10, 10)),
    ],
    ids=["no-audio", "odd-bytes", "other-rate", "line-count", "lengths-disagree"],
)
def test_a_response_that_does_not_match_the_script_is_refused_but_its_usage_is_kept(tmp_path, bad) -> None:  # type: ignore[no-untyped-def]
    provider, _, storage, ledger = _provider(tmp_path, FakeTransport(bad))

    with pytest.raises(ProviderInvalidResponseError):
        asyncio.run(provider.synthesize_dialogue(_request()))

    (event,) = ledger.events
    assert event.metadata["failed_stage"] == "validate" and event.metadata["output_audio_tokens"] == 403
    assert asyncio.run(storage.get(provider.cache_key(_request()))) is None


@pytest.mark.parametrize(
    ("failure", "expected", "outcome"),
    [
        (ProviderTimeoutError("slow"), ProviderTimeoutError, "ProviderTimeoutError"),
        (RuntimeError("socket closed"), ProviderInvalidResponseError, "transport_error"),
        (asyncio.CancelledError(), asyncio.CancelledError, "cancelled"),
    ],
)
def test_a_partial_report_before_a_broken_stream_is_kept_as_partial(tmp_path, failure, expected, outcome) -> None:  # type: ignore[no-untyped-def]
    transport = FakeTransport(failure, usage=[{"output_audio_tokens": 12}], finished=False)
    provider, _, _, ledger = _provider(tmp_path, transport)

    with pytest.raises(expected):
        asyncio.run(provider.synthesize_dialogue(_request()))

    (event,) = ledger.events
    meta = event.metadata
    assert meta["outcome"] == outcome and meta["usage_status"] == "partial"
    assert meta["output_audio_tokens"] == 12 and meta["input_text_tokens"] is None  # unknown, not zero


def test_an_attempt_that_heard_nothing_reports_unknown_not_zero(tmp_path) -> None:
    provider, _, _, ledger = _provider(tmp_path, FakeTransport(ProviderUnavailableError("x"), usage=[], finished=False))

    with pytest.raises(ProviderUnavailableError):
        asyncio.run(provider.synthesize_dialogue(_request()))

    meta = ledger.events[0].metadata
    assert meta["usage_status"] == "unknown" and meta["output_audio_tokens"] is None


def test_junk_counts_are_not_kept() -> None:
    attempt = PodcastAttempt()
    for junk in (
        {"output_audio_tokens": True},
        {"output_audio_tokens": -3},
        {"output_audio_tokens": float("nan")},
        {"output_audio_tokens": float("inf")},
        {"output_audio_tokens": 1.5},
        {"output_audio_tokens": "9"},
        {"text": "not a count"},
        None,
        [],
    ):
        attempt.add_usage(junk)
    assert attempt.usage_reports == [] and attempt.usage_status() == "unknown"

    attempt.add_usage({"input_text_tokens": 0, "output_audio_tokens": 308.0, "prompt": "secret text"})
    assert attempt.usage_reports == [{"input_text_tokens": 0, "output_audio_tokens": 308}]


def test_the_speech_counts_reach_the_safe_report_and_the_totals(tmp_path) -> None:
    provider, _, _, ledger = _provider(tmp_path)
    asyncio.run(provider.synthesize_dialogue(_request()))
    failed, *_ = _provider(tmp_path, FakeTransport(RuntimeError("x"), usage=[], finished=False))
    failed._ledger = ledger  # type: ignore[attr-defined]
    with pytest.raises(ProviderInvalidResponseError):
        asyncio.run(failed.synthesize_dialogue(_request()))

    report = usage_diagnostics(ledger)
    first, second = (safe_usage_event(event) for event in ledger.events)
    assert (first["input_text_tokens"], first["output_audio_tokens"], first["usage_status"]) == (0, 403, "complete")
    assert second["output_audio_tokens"] is None and second["failed_stage"] == "transport"
    assert report["usage"]["output_audio_tokens"] == 403  # type: ignore[index]
    assert report["usage"]["usage_incomplete_calls"] == 1 and report["usage"]["cost_unknown_calls"] == 2  # type: ignore[index]
    assert "刚听完" not in json.dumps(report, ensure_ascii=False)


def test_unverified_values_fail_before_any_call(tmp_path) -> None:
    provider, transport, *_ = _provider(tmp_path)

    with pytest.raises(ProviderConfigurationError, match="speech rate"):
        asyncio.run(provider.synthesize_dialogue(_request(speed=10.0)))
    with pytest.raises(ProviderConfigurationError, match="format"):
        asyncio.run(provider.synthesize_dialogue(_request(audio_format="mp3")))
    assert transport.scripts == [] and provider._ledger.events == []  # type: ignore[attr-defined]


def test_a_segment_is_voiced_through_the_adapter_and_restored_without_a_second_request(tmp_path) -> None:
    provider, transport, storage, _ = _provider(tmp_path)
    materializer = NarrationMaterializer(
        MockTTSProvider(storage), storage,
        dialogue_speech=provider, dialogue_voices=VOICE_COMBINATION_B,
        dialogue_speed=float(SPEECH_RATE_B), dialogue_format="wav",
    )  # fmt: skip
    segment = NarrationSegment(
        id="c:narration:0", chapter_id="c", order=1, state=SegmentState.SCRIPT_READY,
        planned_duration_seconds=10, title="t", dialogue=_block(),
    )  # fmt: skip

    asyncio.run(materializer.materialize(segment))

    assert segment.state is SegmentState.AUDIO_READY and segment.actual_duration_seconds == 8
    snapshot = segment.dialogue_audio
    assert snapshot is not None
    assert (snapshot.provider, snapshot.protocol_version, snapshot.audio_format) == (
        "doubao_podcast", DOUBAO_PODCAST_PROTOCOL, "wav",
    )  # fmt: skip
    again = segment.model_copy(update={"state": SegmentState.SCRIPT_READY})
    other = NarrationMaterializer(MockTTSProvider(storage), storage, dialogue_speech=provider)
    asyncio.run(other.materialize(again))
    assert len(transport.scripts) == 1 and again.asset_ref == segment.asset_ref


# --- the frames ------------------------------------------------------------------------------


def _server(event: frames.Event | int, payload: bytes = b"{}", *, session: str = "s", type_: frames.MsgType = frames.MsgType.FULL_SERVER_RESPONSE) -> bytes:
    return frames.build_frame(event, session_id=session, payload=payload, type_=type_)  # type: ignore[arg-type]


def _json(**fields: Any) -> bytes:
    return json.dumps(fields, ensure_ascii=False).encode()


def test_client_frames_have_the_layout_the_service_expects() -> None:
    start = frames.start_connection()
    assert start == bytes([0x11, 0x14, 0x10, 0x00]) + struct.pack(">i", 1) + struct.pack(">I", 2) + b"{}"
    session = frames.start_session("abc", b'{"a":1}')
    assert session == (
        bytes([0x11, 0x14, 0x10, 0x00]) + struct.pack(">i", 100) + struct.pack(">I", 3) + b"abc"
        + struct.pack(">I", 7) + b'{"a":1}'
    )  # fmt: skip
    assert frames.finish_session("abc")[4:8] == struct.pack(">i", 102)


def test_server_frames_are_parsed_for_each_shape_the_exchange_uses() -> None:
    audio = frames.parse_server_frame(_server(361, b"\x01\x02\x03\x04", type_=frames.MsgType.AUDIO_ONLY_SERVER))
    assert audio.event == frames.Event.PODCAST_ROUND_RESPONSE and audio.payload == b"\x01\x02\x03\x04"
    assert audio.session_id == "s"
    started = frames.parse_server_frame(_server(frames.Event.CONNECTION_STARTED))
    assert started.event == frames.Event.CONNECTION_STARTED and started.session_id == ""
    error = frames.parse_server_frame(
        bytes([0x11, 0xF0, 0x10, 0x00]) + struct.pack(">I", 45000001) + struct.pack(">I", 3) + b"bad"
    )
    assert error.type is frames.MsgType.ERROR and error.error_code == 45000001
    unknown = frames.parse_server_frame(_server(999))
    assert unknown.event == 999


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x11\x94",
        bytes([0x11, 0x94, 0x11, 0x00]) + struct.pack(">i", 152) + struct.pack(">I", 0) + struct.pack(">I", 0),  # gzip
        _server(152) + b"extra",
        _server(152)[:-3],
        bytes([0x21, 0x94, 0x10, 0x00]) + b"\x00" * 8,
        bytes([0x11, 0x84, 0x10, 0x00]) + b"\x00" * 8,  # type 8 is unknown
    ],
    ids=["empty", "short", "compressed", "trailing", "truncated", "bad-version", "bad-type"],
)
def test_frames_it_does_not_understand_are_refused(data: bytes) -> None:
    with pytest.raises(ProviderInvalidResponseError):
        frames.parse_server_frame(data)


# --- the transport, over a fake WebSocket ----------------------------------------------------


class FakeSocket:
    def __init__(self, incoming: list[bytes | str | BaseException]) -> None:
        self.incoming = list(incoming)
        self.sent: list[bytes] = []
        self.closed = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> bytes | str:
        if not self.incoming:
            await asyncio.sleep(3600)
        item = self.incoming.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True


class Connector:
    def __init__(self, socket: FakeSocket | BaseException) -> None:
        self.socket = socket
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    async def __call__(self, url: str, headers: Mapping[str, str]) -> FakeSocket:
        self.calls.append((url, dict(headers)))
        if isinstance(self.socket, BaseException):
            raise self.socket
        return self.socket


def _script() -> PodcastScript:
    provider = DoubaoPodcastSpeechProvider(FakeTransport(), None)  # type: ignore[arg-type]
    return provider._script(_request())  # type: ignore[attr-defined]


def _round(index: int, *, seconds: float, speaker: str, text: str, reported: float | None = None) -> list[bytes]:
    pcm = _pcm(seconds)
    info = {"speaker": speaker, "text": text, "round_id": index}
    end: dict[str, Any] = {"is_error": False}
    if reported is not None:
        end["audio_duration"] = reported
    half = len(pcm) // 2
    return [
        _server(360, _json(**info)),
        _server(361, pcm[:half], type_=frames.MsgType.AUDIO_ONLY_SERVER),
        _server(361, pcm[half:], type_=frames.MsgType.AUDIO_ONLY_SERVER),
        _server(362, _json(**end)),
    ]


def _good_session() -> list[bytes | str | BaseException]:
    return [
        _server(frames.Event.CONNECTION_STARTED),
        _server(frames.Event.SESSION_STARTED),
        *_round(0, seconds=1.0, speaker=A_VOICE, text=LINE_A, reported=1.0),
        _server(frames.Event.USAGE_RESPONSE, _json(usage={"input_text_tokens": 0, "output_audio_tokens": 403, "secret": "x"})),
        *_round(1, seconds=2.0, speaker=B_VOICE, text=LINE_B, reported=2.0),
        _server(frames.Event.USAGE_RESPONSE, _json(usage={"input_text_tokens": 0, "output_audio_tokens": 308})),
        _server(frames.Event.PODCAST_END),
        _server(frames.Event.SESSION_FINISHED),
        _server(frames.Event.CONNECTION_FINISHED),
    ]


def _transport(connector: Connector, **options: Any) -> DoubaoPodcastWebSocketTransport:
    return DoubaoPodcastWebSocketTransport("k-secret", connect=connector, **options)


def _run(transport: DoubaoPodcastWebSocketTransport, attempt: PodcastAttempt | None = None) -> PodcastAudio:
    return asyncio.run(transport.synthesize(_script(), attempt or PodcastAttempt()))


def test_a_complete_session_returns_the_audio_line_by_line_and_the_counts() -> None:
    socket = FakeSocket(_good_session())
    connector = Connector(socket)
    attempt = PodcastAttempt()

    audio = _run(_transport(connector), attempt)

    assert audio.sample_rate == 24000
    assert audio.line_byte_lengths == (len(_pcm(1.0)), len(_pcm(2.0))) and len(audio.pcm) == len(_pcm(3.0))
    assert attempt.usage_reports == [
        {"input_text_tokens": 0, "output_audio_tokens": 403},
        {"input_text_tokens": 0, "output_audio_tokens": 308},
    ]
    assert attempt.total("output_audio_tokens") == 711 and attempt.usage_status() == "complete"
    assert attempt.rounds_completed == 2 and attempt.session_finished and socket.closed
    # one connection, the verified handshake, a request the service has already accepted once
    (url, headers), = connector.calls
    assert url == "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"
    assert headers["X-Api-Key"] == "k-secret" and headers["X-Api-Resource-Id"] == "volc.service_type.10050"
    assert headers["X-Api-Request-Id"] == attempt.request_id
    events = [struct.unpack(">i", data[4:8])[0] for data in socket.sent]
    assert events == [1, 100, 102, 2]  # StartConnection, StartSession, FinishSession, FinishConnection
    payload = json.loads(socket.sent[1][4 + 4 + 4 + 36 + 4 :])
    assert payload == {
        "action": 3,
        "nlp_texts": [{"speaker": A_VOICE, "text": LINE_A}, {"speaker": B_VOICE, "text": LINE_B}],
        "use_head_music": False,
        "use_tail_music": False,
        "input_info": {"return_audio_url": False},
        "speaker_info": {"random_order": False, "speakers": [A_VOICE, B_VOICE]},
        "audio_config": {"format": "pcm", "sample_rate": 24000, "speech_rate": 0},
    }


def test_the_api_key_is_required_and_never_shown() -> None:
    with pytest.raises(ProviderConfigurationError, match="DOUBAO_PODCAST_API_KEY"):
        DoubaoPodcastWebSocketTransport("")
    assert "k-secret" not in repr(_transport(Connector(FakeSocket([]))))


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, ProviderAuthenticationError), (403, ProviderPermissionError), (429, ProviderRateLimitError), (500, ProviderUnavailableError)],
)
def test_the_handshake_status_is_mapped_without_the_body(status, expected) -> None:  # type: ignore[no-untyped-def]
    class Rejected(Exception):
        def __init__(self) -> None:
            super().__init__("body with secrets")
            self.response = type("R", (), {"status_code": status})()

    connector = Connector(Rejected())
    with pytest.raises(expected) as raised:
        _run(_transport(connector))
    assert "secrets" not in str(raised.value) and len(connector.calls) == 1  # no retry


def test_a_service_error_frame_keeps_only_its_number() -> None:
    error = bytes([0x11, 0xF0, 0x10, 0x00]) + struct.pack(">I", 55000031) + struct.pack(">I", 6) + b"secret"
    socket = FakeSocket([_server(frames.Event.CONNECTION_STARTED), error])
    with pytest.raises(ProviderRequestError, match="55000031") as raised:
        _run(_transport(Connector(socket)))
    assert "secret" not in str(raised.value) and socket.closed


@pytest.mark.parametrize(
    "script",
    [
        # a different line than the one asked for
        [*_good_session()[:2], *_round(0, seconds=1.0, speaker=A_VOICE, text="别的话")],
        # a different voice
        [*_good_session()[:2], *_round(0, seconds=1.0, speaker=B_VOICE, text=LINE_A)],
        # audio outside a round
        [*_good_session()[:2], _server(361, b"\x00\x00", type_=frames.MsgType.AUDIO_ONLY_SERVER)],
        # a round that reports an error
        [*_good_session()[:2], _server(360, _json(speaker=A_VOICE, text=LINE_A)), _server(362, _json(is_error=True))],
        # a reported length far from the audio
        [*_good_session()[:2], *_round(0, seconds=1.0, speaker=A_VOICE, text=LINE_A, reported=30.0)],
        # an event it has not seen
        [*_good_session()[:2], _server(777)],
        # a non-binary message
        [*_good_session()[:2], "hello"],
        # unreadable JSON
        [*_good_session()[:2], _server(360, b"not json")],
        # a failed connection or session
        [_server(frames.Event.CONNECTION_FAILED)],
        [*_good_session()[:1], _server(frames.Event.SESSION_FAILED)],
    ],
    ids=["other-text", "other-voice", "orphan-audio", "round-error", "length", "unknown-event", "text-frame", "bad-json", "conn-failed", "session-failed"],
)
def test_anything_unexpected_ends_the_attempt_without_returning_audio(script) -> None:  # type: ignore[no-untyped-def]
    socket = FakeSocket(list(script))
    connector = Connector(socket)
    with pytest.raises((ProviderInvalidResponseError, ProviderUnavailableError)):
        _run(_transport(connector))
    assert socket.closed and len(connector.calls) == 1


def test_a_dialogue_that_ends_early_is_incomplete_and_keeps_the_usage_it_saw() -> None:
    socket = FakeSocket(
        [
            *_good_session()[:2],
            *_round(0, seconds=1.0, speaker=A_VOICE, text=LINE_A),
            _server(frames.Event.USAGE_RESPONSE, _json(usage={"output_audio_tokens": 403})),
            _server(frames.Event.SESSION_FINISHED),
        ]
    )
    attempt = PodcastAttempt()
    with pytest.raises(ProviderIncompleteResponseError):
        _run(_transport(Connector(socket)), attempt)
    assert attempt.total("output_audio_tokens") == 403 and attempt.usage_status() == "partial"
    assert attempt.rounds_completed == 1 and not attempt.session_finished


def test_a_connection_that_drops_midway_is_unavailable_and_not_retried() -> None:
    socket = FakeSocket([*_good_session()[:2], *_round(0, seconds=1.0, speaker=A_VOICE, text=LINE_A), ConnectionError("gone")])
    connector = Connector(socket)
    with pytest.raises(ProviderUnavailableError):
        _run(_transport(connector))
    assert len(connector.calls) == 1 and socket.closed


def test_silence_times_out_and_closes() -> None:
    socket = FakeSocket([_server(frames.Event.CONNECTION_STARTED)])  # then nothing
    with pytest.raises(ProviderTimeoutError):
        _run(_transport(Connector(socket), receive_timeout=0.05))
    assert socket.closed


def test_the_whole_call_has_a_deadline() -> None:
    class Slow(FakeSocket):
        async def recv(self) -> bytes | str:
            await asyncio.sleep(0.02)
            return _server(frames.Event.USAGE_RESPONSE)  # forever "usage", never the start

    socket = Slow([])
    with pytest.raises(ProviderTimeoutError):
        _run(_transport(Connector(socket), total_timeout=0.1))
    assert socket.closed


def test_cancelling_closes_the_connection_and_propagates() -> None:
    socket = FakeSocket([_server(frames.Event.CONNECTION_STARTED)])

    async def go() -> None:
        task = asyncio.create_task(_transport(Connector(socket)).synthesize(_script(), PodcastAttempt()))
        await asyncio.sleep(0.05)
        task.cancel()
        await task

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(go())
    assert socket.closed


def test_audio_beyond_the_local_guard_stops_the_attempt() -> None:
    socket = FakeSocket([*_good_session()[:2], *_round(0, seconds=2.0, speaker=A_VOICE, text=LINE_A)])
    with pytest.raises(ProviderInvalidResponseError, match="guard"):
        _run(_transport(Connector(socket), max_audio_seconds=1.0))


def test_a_polite_close_that_fails_does_not_throw_away_a_complete_dialogue() -> None:
    session = _good_session()[:-1]  # the service never answers FinishConnection
    socket = FakeSocket([*session, ConnectionError("closed")])
    audio = _run(_transport(Connector(socket)))
    assert len(audio.pcm) == len(_pcm(3.0))


def test_through_the_adapter_a_session_is_stored_and_recorded_end_to_end(tmp_path) -> None:
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    ledger = UsageLedger()
    provider = DoubaoPodcastSpeechProvider(_transport(Connector(FakeSocket(_good_session()))), storage, ledger=ledger)

    asset = asyncio.run(provider.synthesize_dialogue(_request()))

    assert asset.duration == 3
    (event,) = ledger.events
    assert event.metadata["output_audio_tokens"] == 711 and event.metadata["usage_status"] == "complete"
    assert event.request_id and event.metadata["rounds_completed"] == 2
