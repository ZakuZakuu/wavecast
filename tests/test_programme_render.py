from __future__ import annotations

import asyncio
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from wavecast.arrangement.models import AudioClip, GainPoint, MixPlan
from wavecast.rendering import (
    ProgramImmutabilityError,
    hls_playlist,
    render_program_prefix,
    slice_mix_plan,
)
from wavecast.storage import LocalObjectStorageProvider


def _wav_bytes(duration_seconds: float, frequency: float = 220) -> bytes:
    sample_rate = 8000
    frame_count = int(sample_rate * duration_seconds)
    payload = bytearray()
    for index in range(frame_count):
        value = int(9000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        payload.extend(struct.pack("<hh", value, value))
    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(payload))
    return buffer.getvalue()


def _plan(
    duration_seconds: float,
    *,
    first_gain: float = 1.0,
) -> MixPlan:
    return MixPlan(
        episode_id="program-render-fixture",
        duration_seconds=duration_seconds,
        clips=(
            AudioClip(
                id="music-a:music",
                segment_id="music-a",
                source_url="/api/assets/audio/source.wav",
                lane="MUSIC",
                timeline_start_seconds=0,
                source_offset_seconds=0,
                playable_duration_seconds=duration_seconds,
                gain_automation=(
                    GainPoint(offset_seconds=0, gain=first_gain),
                    GainPoint(offset_seconds=duration_seconds, gain=1),
                ),
            ),
        ),
        segment_starts={"music-a": 0},
    )


def test_slice_mix_plan_preserves_source_and_gain_at_absolute_window() -> None:
    plan = _plan(12, first_gain=0.4)

    sliced = slice_mix_plan(plan, 3, 9)

    clip = sliced.clips[0]
    assert sliced.duration_seconds == 6
    assert clip.timeline_start_seconds == 0
    assert clip.source_offset_seconds == 3
    assert clip.playable_duration_seconds == 6
    assert clip.gain_automation[0].offset_seconds == 0
    assert clip.gain_automation[-1].offset_seconds == 6
    assert clip.gain_automation[0].gain == pytest.approx(0.55)
    assert clip.gain_automation[-1].gain == pytest.approx(0.85)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_program_render_appends_immutable_chunks_and_reuses_frozen_prefix(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        await storage.put("source.wav", _wav_bytes(24), "audio/wav")

        first = await render_program_prefix(
            _plan(16),
            storage,
            holdback_seconds=3,
        )
        assert first.rendered_frontier_seconds > 11
        assert len(first.chunks) >= 2
        assert first.complete is False

        second = await render_program_prefix(
            _plan(22),
            storage,
            holdback_seconds=3,
        )
        assert second.rendered_frontier_seconds > first.rendered_frontier_seconds
        assert len(second.chunks) > len(first.chunks)
        assert second.chunks[: len(first.chunks)] == first.chunks

        playlist = hls_playlist(second)
        assert "#EXT-X-PLAYLIST-TYPE:EVENT" in playlist
        assert "#EXT-X-ENDLIST" not in playlist
        for chunk in second.chunks:
            assert chunk.audio_url in playlist
            stored = await storage.get(chunk.asset_key)
            assert stored is not None
            assert stored.content_type == "video/mp2t"
            assert stored.content

        final = await render_program_prefix(
            _plan(22),
            storage,
            complete=True,
            holdback_seconds=3,
        )
        assert final.rendered_frontier_seconds == pytest.approx(22, abs=0.15)
        assert final.complete is True
        assert len(final.chunks) > len(second.chunks)
        assert "#EXT-X-ENDLIST" in hls_playlist(final)

    asyncio.run(run())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_program_render_rejects_rewrite_behind_frozen_frontier(tmp_path: Path) -> None:
    async def run() -> None:
        storage = LocalObjectStorageProvider(tmp_path / "audio")
        await storage.put("source.wav", _wav_bytes(24), "audio/wav")
        frozen = await render_program_prefix(
            _plan(16),
            storage,
            holdback_seconds=3,
        )
        assert frozen.chunks

        with pytest.raises(ProgramImmutabilityError, match="rewrites frozen"):
            await render_program_prefix(
                _plan(22, first_gain=0.5),
                storage,
                holdback_seconds=3,
            )

    asyncio.run(run())
