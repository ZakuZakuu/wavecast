from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest
from wavecast.arrangement.models import AudioClip, GainPoint, MixPlan
from wavecast.rendering import MixRenderError, build_filter_graph, render_mix


def make_wav(path: Path, duration_seconds: float, frequency: float) -> None:
    sample_rate = 8000
    frames = int(sample_rate * duration_seconds)
    samples = bytearray()
    for index in range(frames):
        value = int(12000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        samples.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(samples))


def canonical_plan() -> MixPlan:
    return MixPlan(
        episode_id="render-fixture",
        duration_seconds=3.5,
        clips=(
            AudioClip(
                id="music-a:music",
                segment_id="music-a",
                source_url="/api/assets/audio/music-a.wav",
                lane="MUSIC",
                timeline_start_seconds=0,
                source_offset_seconds=0.25,
                playable_duration_seconds=2,
                gain_automation=(
                    GainPoint(offset_seconds=0, gain=1),
                    GainPoint(offset_seconds=1, gain=0.5),
                    GainPoint(offset_seconds=2, gain=0),
                ),
            ),
            AudioClip(
                id="voice-a:voice",
                segment_id="voice-a",
                source_url="/api/assets/audio/voice-a.wav",
                lane="VOICE",
                timeline_start_seconds=1,
                source_offset_seconds=0,
                playable_duration_seconds=1,
                gain_automation=(
                    GainPoint(offset_seconds=0, gain=0),
                    GainPoint(offset_seconds=0.08, gain=1),
                    GainPoint(offset_seconds=1, gain=0),
                ),
            ),
            AudioClip(
                id="music-b:music",
                segment_id="music-b",
                source_url="/api/assets/audio/music-b.wav",
                lane="MUSIC",
                timeline_start_seconds=1.5,
                source_offset_seconds=0,
                playable_duration_seconds=2,
                gain_automation=(
                    GainPoint(offset_seconds=0, gain=0),
                    GainPoint(offset_seconds=0.5, gain=1),
                    GainPoint(offset_seconds=2, gain=1),
                ),
            ),
        ),
        segment_starts={"music-a": 0, "voice-a": 1, "music-b": 1.5},
    )


def test_filter_graph_is_deterministic_and_uses_canonical_timing() -> None:
    plan = canonical_plan()
    first = build_filter_graph(plan)
    second = build_filter_graph(plan)

    assert first == second
    assert "atrim=start=0.25:duration=2" in first
    assert "adelay=1000:all=1" in first
    assert "adelay=1500:all=1" in first
    assert "if(lt(t,1)" in first
    assert "amix=inputs=3" in first
    assert "atrim=duration=3.5" in first


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_render_mix_generates_mp3_with_plan_duration(tmp_path: Path) -> None:
    plan = canonical_plan()
    inputs = {}
    for name, frequency in (("music-a", 220), ("voice-a", 440), ("music-b", 330)):
        path = tmp_path / f"{name}.wav"
        make_wav(path, 3, frequency)
        inputs[f"{name}:music" if name != "voice-a" else "voice-a:voice"] = path

    output = tmp_path / "mixdown.mp3"
    result = render_mix(plan, inputs, output)

    assert result.duration_seconds == plan.duration_seconds
    assert output.is_file()
    assert output.stat().st_size > 0

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert float(probe.stdout.strip()) == pytest.approx(plan.duration_seconds, abs=0.08)


def test_render_mix_fails_without_a_resolved_input(tmp_path: Path) -> None:
    plan = canonical_plan()
    with pytest.raises(MixRenderError, match="resolved mix input"):
        render_mix(
            plan,
            {"music-a:music": tmp_path / "music-a.wav"},
            tmp_path / "mixdown.mp3",
        )
