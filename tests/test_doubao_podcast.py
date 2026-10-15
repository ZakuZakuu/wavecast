"""The Doubao dialogue adapter, driven by a fake transport (no network, no credentials).

What this does not show: the real service's wire protocol, latency, line timings or failures.
The transport is the seam where that is added once an experiment recording exists (ADR 0027).
"""

from __future__ import annotations

import asyncio

import pytest
from wavecast.materialization import NarrationMaterializer
from wavecast.models.dialogue import DialogueBlock, DialoguePurpose, DialogueSpeaker, DialogueTurn
from wavecast.models.episode import NarrationSegment, SegmentState
from wavecast.providers.doubao_podcast import (
    DOUBAO_PODCAST_PROTOCOL,
    DoubaoPodcastSpeechProvider,
    PodcastAudio,
    PodcastScript,
)
from wavecast.providers.doubao_voices import SPEECH_RATE_B, VOICE_COMBINATION_B
from wavecast.providers.errors import (
    ProviderConfigurationError,
    ProviderInvalidResponseError,
    ProviderTimeoutError,
)
from wavecast.providers.fakes import MockTTSProvider
from wavecast.providers.speech import SpeechRequest
from wavecast.providers.usage import UsageLedger
from wavecast.storage import LocalObjectStorageProvider


def _block(text_b: str = "我也这么想。") -> DialogueBlock:
    return DialogueBlock(
        block_id="b1",
        slot_id="s1",
        story_id="st-1",
        purpose=DialoguePurpose.STORY,
        turns=[
            DialogueTurn(speaker=DialogueSpeaker.A, text="刚听完这首歌。", tts_text=None, fact_refs=[]),
            DialogueTurn(speaker=DialogueSpeaker.B, text=text_b, tts_text=None, fact_refs=[]),
        ],
        duration_seconds=10,
    )


def _request(block: DialogueBlock | None = None, **changes: object) -> SpeechRequest:
    base: dict[str, object] = dict(speed=float(SPEECH_RATE_B), audio_format="mp3")
    return SpeechRequest.dialogue(block or _block(), list(VOICE_COMBINATION_B), **{**base, **changes})  # type: ignore[arg-type]


class FakeTransport:
    def __init__(self, result: PodcastAudio | BaseException | None = None) -> None:
        self.result = result if result is not None else PodcastAudio(
            audio=b"ID3fake", audio_format="mp3", duration_seconds=7.2,
            line_timings=((0.0, 3.0), (3.0, 7.2)), request_id="req-1", billed_characters=14,
        )  # fmt: skip
        self.scripts: list[PodcastScript] = []

    async def synthesize(self, script: PodcastScript) -> PodcastAudio:
        self.scripts.append(script)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _provider(tmp_path, transport: FakeTransport | None = None):  # type: ignore[no-untyped-def]
    storage = LocalObjectStorageProvider(tmp_path / "audio")
    ledger = UsageLedger()
    transport = transport or FakeTransport()
    return DoubaoPodcastSpeechProvider(transport, storage, ledger=ledger), transport, storage, ledger


def test_the_script_is_sent_exactly_with_each_host_s_own_voice(tmp_path) -> None:
    provider, transport, _, _ = _provider(tmp_path)

    asset = asyncio.run(provider.synthesize_dialogue(_request()))

    (script,) = transport.scripts
    assert [(line.speaker, line.voice_id, line.text) for line in script.lines] == [
        ("A", VOICE_COMBINATION_B[0].voice_id, "刚听完这首歌。"),
        ("B", VOICE_COMBINATION_B[1].voice_id, "我也这么想。"),
    ]
    assert script.speed == 0 and script.audio_format == "mp3"
    assert asset.duration == 8  # 7.2 s rounded up: the timeline plans with whole seconds
    assert asset.asset_id.endswith(".mp3") and asset.asset_id.startswith("dialogue-")
    assert asset.metadata["turn_timings"][1] == {"speaker": "B", "start": 3.0, "end": 7.2}


def test_the_audio_is_stored_where_the_materializer_finds_it_again(tmp_path) -> None:
    provider, _, storage, _ = _provider(tmp_path)
    asset = asyncio.run(provider.synthesize_dialogue(_request()))

    stored = asyncio.run(storage.get(asset.asset_id))

    assert stored is not None and stored.content == b"ID3fake"
    assert stored.metadata["duration_seconds"] == 8


def test_the_cache_key_follows_everything_that_changes_what_is_heard(tmp_path) -> None:
    provider, *_ = _provider(tmp_path)
    base = provider.cache_key(_request())

    assert provider.cache_key(_request()) == base
    assert provider.cache_key(_request(_block("换一句话。"))) != base
    assert provider.cache_key(_request(speed=10.0)) != base
    assert provider.cache_key(_request(audio_format="wav")) != base
    swapped = SpeechRequest.dialogue(
        _block(),
        [
            VOICE_COMBINATION_B[0],
            VOICE_COMBINATION_B[1].model_copy(update={"voice_id": "another_voice"}),
        ],
        speed=0.0,
        audio_format="mp3",
    )
    assert provider.cache_key(swapped) != base


def test_every_outcome_leaves_a_usage_record_with_no_text(tmp_path) -> None:
    provider, _, _, ledger = _provider(tmp_path)
    asyncio.run(provider.synthesize_dialogue(_request()))

    (event,) = ledger.events
    assert (event.provider, event.operation, event.request_id) == ("doubao_podcast", "dialogue_speech", "req-1")
    assert event.usage_characters == 14  # what the vendor billed
    assert event.metadata["outcome"] == "ok" and event.metadata["protocol"] == DOUBAO_PODCAST_PROTOCOL
    assert "刚听完" not in str(event.model_dump())


@pytest.mark.parametrize(
    ("failure", "expected", "outcome"),
    [
        (ProviderTimeoutError("slow"), ProviderTimeoutError, "ProviderTimeoutError"),
        (RuntimeError("socket closed"), ProviderInvalidResponseError, "transport_error"),
    ],
)
def test_failures_are_mapped_and_recorded(tmp_path, failure, expected, outcome) -> None:  # type: ignore[no-untyped-def]
    provider, _, storage, ledger = _provider(tmp_path, FakeTransport(failure))

    with pytest.raises(expected):
        asyncio.run(provider.synthesize_dialogue(_request()))

    (event,) = ledger.events
    assert event.metadata["outcome"] == outcome
    assert event.usage_characters == len("刚听完这首歌。我也这么想。")  # sent, since nothing was billed
    assert asyncio.run(storage.get(provider.cache_key(_request()))) is None


def test_cancellation_is_recorded_and_propagates(tmp_path) -> None:
    provider, _, _, ledger = _provider(tmp_path, FakeTransport(asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.synthesize_dialogue(_request()))

    assert ledger.events[0].metadata["outcome"] == "cancelled"


@pytest.mark.parametrize(
    "bad",
    [
        PodcastAudio(audio=b"", audio_format="mp3", duration_seconds=5),
        PodcastAudio(audio=b"x", audio_format="wav", duration_seconds=5),
        PodcastAudio(audio=b"x", audio_format="mp3", duration_seconds=0),
        PodcastAudio(audio=b"x", audio_format="mp3", duration_seconds=float("nan")),
        PodcastAudio(audio=b"x", audio_format="mp3", duration_seconds=5, line_timings=((0.0, 5.0),)),
    ],
    ids=["no-audio", "other-format", "no-duration", "nan-duration", "timings-mismatch"],
)
def test_a_response_that_does_not_match_the_script_is_refused(tmp_path, bad) -> None:  # type: ignore[no-untyped-def]
    provider, _, storage, ledger = _provider(tmp_path, FakeTransport(bad))

    with pytest.raises(ProviderInvalidResponseError):
        asyncio.run(provider.synthesize_dialogue(_request()))

    assert len(ledger.events) == 1
    assert asyncio.run(storage.get(provider.cache_key(_request()))) is None


def test_values_outside_the_vendor_s_range_fail_before_any_call(tmp_path) -> None:
    provider, transport, *_ = _provider(tmp_path)

    with pytest.raises(ProviderConfigurationError, match="speech rate"):
        asyncio.run(provider.synthesize_dialogue(_request(speed=900.0)))
    with pytest.raises(ProviderConfigurationError, match="format"):
        asyncio.run(provider.synthesize_dialogue(_request(audio_format="ogg")))
    assert transport.scripts == []


def test_a_segment_is_voiced_through_the_adapter_and_records_what_it_was_made_with(tmp_path) -> None:
    provider, transport, storage, _ = _provider(tmp_path)
    materializer = NarrationMaterializer(
        MockTTSProvider(storage), storage,
        dialogue_speech=provider, dialogue_voices=VOICE_COMBINATION_B,
        dialogue_speed=float(SPEECH_RATE_B), dialogue_format="mp3",
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
        "doubao_podcast", DOUBAO_PODCAST_PROTOCOL, "mp3",
    )  # fmt: skip
    # Restoring it again, even under a different configuration, makes no second request.
    again = segment.model_copy(update={"state": SegmentState.SCRIPT_READY})
    other = NarrationMaterializer(MockTTSProvider(storage), storage, dialogue_speech=provider)
    asyncio.run(other.materialize(again))
    assert len(transport.scripts) == 1 and again.asset_ref == segment.asset_ref
