"""Sources are brought to one loudness and the mix is limited, without touching the timeline."""

from __future__ import annotations

import math
import re
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest
from wavecast.arrangement.models import AudioClip, MixPlan
from wavecast.rendering import render_mix
from wavecast.rendering.ffmpeg import (
    PEAK_LIMIT,
    TARGET_LUFS,
    build_filter_graph,
    loudness_gains_db,
    measure_integrated_lufs,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")


def tone(path: Path, seconds: float, amplitude: float, frequency: float = 440.0) -> None:
    rate = 8000
    frames = bytearray()
    for i in range(int(rate * seconds)):
        value = int(32767 * amplitude * math.sin(2 * math.pi * frequency * i / rate))
        frames.extend(struct.pack("<hh", value, value))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))


def clip(clip_id: str, lane: str, start: float, seconds: float) -> AudioClip:
    return AudioClip(
        id=clip_id,
        segment_id=clip_id.split(":")[0],
        source_url="/x",
        lane=lane,
        timeline_start_seconds=start,
        source_offset_seconds=0,
        playable_duration_seconds=seconds,
    )


def lufs_and_true_peak(path: Path) -> tuple[float, float]:
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, check=True,
    ).stderr.decode()
    integrated = float(re.findall(r"I:\s*(-?[\d.]+) LUFS", log)[-1])
    peak = float(re.findall(r"Peak:\s*(-?[\d.]+) dBFS", log)[-1])
    return integrated, peak


def test_a_quiet_voice_and_a_hot_song_are_brought_to_the_same_loudness(tmp_path: Path) -> None:
    voice, song = tmp_path / "voice.wav", tmp_path / "song.wav"
    tone(voice, 4, 0.08)
    tone(song, 4, 0.5, 880.0)
    plan = MixPlan(
        episode_id="e", duration_seconds=4,
        clips=(clip("voice:voice", "VOICE", 0, 4), clip("song:music", "MUSIC", 0, 4)),
        segment_starts={"voice": 0, "song": 0},
    )

    gains = loudness_gains_db(plan, {"voice:voice": voice, "song:music": song})

    for path, key in ((voice, "voice:voice"), (song, "song:music")):
        measured = measure_integrated_lufs(path)
        assert measured is not None
        assert measured + gains[key] == pytest.approx(TARGET_LUFS, abs=0.6)


def test_a_source_that_cannot_be_measured_is_left_alone(tmp_path: Path) -> None:
    silent = tmp_path / "silent.wav"
    tone(silent, 2, 0.0)
    plan = MixPlan(episode_id="e", duration_seconds=2, clips=(clip("s:voice", "VOICE", 0, 2),), segment_starts={"s": 0})

    assert loudness_gains_db(plan, {"s:voice": silent}) == {"s:voice": 0.0}


def test_the_mix_keeps_its_length_and_its_true_peak_under_the_limit(tmp_path: Path) -> None:
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    tone(a, 3, 0.95, 300.0)
    tone(b, 3, 0.95, 500.0)
    plan = MixPlan(
        episode_id="e", duration_seconds=3,
        clips=(clip("a:music", "MUSIC", 0, 3), clip("b:voice", "VOICE", 0, 3)),
        segment_starts={"a": 0, "b": 0},
    )
    out = tmp_path / "mix.wav"
    gains = {"a:music": 6.0, "b:voice": 6.0}  # deliberately hot: the limiter has to hold it
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(a), "-i", str(b),
         "-filter_complex", build_filter_graph(plan, gains), "-map", "[mixout]", str(out)],
        check=True,
    )

    with wave.open(str(out)) as result:
        seconds = result.getnframes() / result.getframerate()
    _loudness, true_peak = lufs_and_true_peak(out)

    assert seconds == pytest.approx(3.0, abs=0.02)  # the limiter neither shortens nor delays the timeline
    assert true_peak <= -1.5
    assert PEAK_LIMIT < 0.8


def test_the_end_of_a_host_clip_is_still_there_after_limiting(tmp_path: Path) -> None:
    voice = tmp_path / "voice.wav"
    tone(voice, 2, 0.5)
    plan = MixPlan(episode_id="e", duration_seconds=3, clips=(clip("v:voice", "VOICE", 0.5, 2),), segment_starts={"v": 0.5})
    out = tmp_path / "mix.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(voice),
         "-filter_complex", build_filter_graph(plan, {"v:voice": 0.0}), "-map", "[mixout]", str(out)],
        check=True,
    )
    with wave.open(str(out)) as result:
        rate = result.getframerate()
        frames = result.readframes(result.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    last_loud = max(i for i, value in enumerate(samples) if abs(value) > 2000) / 2 / rate  # two channels

    assert last_loud == pytest.approx(2.5, abs=0.05)  # the clip ends at 0.5 + 2.0 s, not earlier
    assert render_mix is not None


def test_without_the_loudness_rule_the_graph_is_the_one_old_programmes_were_published_with() -> None:
    """Old programmes keep rendering as they did: no extra gain stage and no limiter."""

    plan = MixPlan(
        episode_id="e", duration_seconds=3,
        clips=(clip("a:music", "MUSIC", 0, 3), clip("b:voice", "VOICE", 0, 3)),
        segment_starts={"a": 0, "b": 0},
    )

    legacy = build_filter_graph(plan, None, limiter=False)

    assert "alimiter" not in legacy
    assert legacy.count("stereo,volume=eval=frame") == len(plan.clips)  # no gain stage before each clip's own automation
    assert "alimiter" in build_filter_graph(plan, {"a:music": -3.0})
