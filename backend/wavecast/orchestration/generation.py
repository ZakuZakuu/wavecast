from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from wavecast.models.episode import LiveEpisode, MusicSegment, NarrationSegment, SegmentState
from wavecast.providers import AudioProvider, MockAudioProvider


class GeneratedChapter(BaseModel):
    """One provider-neutral future chapter with independently ready resources."""

    chapter_id: str = Field(min_length=1)
    segments: list[MusicSegment | NarrationSegment] = Field(min_length=1)


class ProgressiveChapterGenerator(Protocol):
    async def generate_next(self, episode: LiveEpisode) -> GeneratedChapter | None: ...


class DeterministicMockProgressiveGenerator:
    """Credential-free chapter producer used by the local runtime and tests."""

    def __init__(self, audio_provider: AudioProvider | None = None) -> None:
        self.audio_provider = audio_provider or MockAudioProvider()
        self.calls = 0

    async def generate_next(self, episode: LiveEpisode) -> GeneratedChapter | None:
        existing_chapters = {segment.chapter_id for segment in episode.segments}
        next_number = next(
            (number for number in range(2, 5) if f"chapter-{number}" not in existing_chapters),
            5,
        )
        self.calls += 1
        if next_number > 4:
            return None

        definitions = {
            2: (
                "segment-narration-1",
                "Host introduction",
                "Welcome to this guided listening journey.",
                "segment-bridge",
                10,
                "mock:bridge",
                "Midnight Transfer",
                "Signal Garden",
            ),
            3: (
                "segment-narration-2",
                "Host connection",
                "Now we connect the next chapter.",
                "segment-resolution",
                11,
                "mock:resolution",
                "Daybreak in Stereo",
                "Southbound FM",
            ),
            4: (
                "segment-narration-3",
                "Host resolution",
                "We close with a final reflection.",
                "segment-finale",
                9,
                "mock:finale",
                "Afterimage Avenue",
                "Southbound FM",
            ),
        }
        (
            narration_id,
            narration_title,
            narration_text,
            music_id,
            narration_duration,
            track_ref,
            music_title,
            artist,
        ) = definitions[next_number]
        chapter_id = f"chapter-{next_number}"
        base_order = episode.ordered_segments[-1].order + 1 if episode.ordered_segments else 0
        narration_source = self.audio_provider.narration_source(
            narration_id, narration_text, narration_duration
        )
        music_source = self.audio_provider.music_source(track_ref)
        return GeneratedChapter(
            chapter_id=chapter_id,
            segments=[
                NarrationSegment(
                    id=narration_id,
                    chapter_id=chapter_id,
                    order=base_order,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=narration_duration,
                    actual_duration_seconds=narration_source.duration_seconds,
                    audio_source_url=narration_source.source_url,
                    asset_ref=narration_source.source_url,
                    title=narration_title,
                    narration_text=narration_text,
                ),
                MusicSegment(
                    id=music_id,
                    chapter_id=chapter_id,
                    order=base_order + 1,
                    state=SegmentState.AUDIO_READY,
                    planned_duration_seconds=music_source.duration_seconds,
                    actual_duration_seconds=music_source.duration_seconds,
                    track_ref=track_ref,
                    audio_source_url=music_source.source_url,
                    title=music_title,
                    artist=artist,
                ),
            ],
        )

