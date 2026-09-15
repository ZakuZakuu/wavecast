from hashlib import sha1
from urllib.parse import quote

from pydantic import BaseModel

from .contracts import AudioAsset, AudioAssetType, AudioSource, SearchResult, TrackMetadata


class FakeSearchProvider:
    async def search(
        self, query: str, *, limit: int = 5, stage: str | None = None
    ) -> list[SearchResult]:
        del stage
        return [
            SearchResult(
                title=f"Mock research for {query}",
                url="https://example.invalid/mock-research",
                snippet="Deterministic fixture result; no network request was made.",
                provider="fake-search",
                query=query,
                score=1.0,
            )
        ][:limit]


class FakeLLMProvider:
    async def structured(self, prompt: str, output_type: type[BaseModel]) -> BaseModel:
        raise NotImplementedError(
            "FakeLLMProvider requires an explicit fixture response per agent contract"
        )


class FakeTTSProvider:
    async def synthesize(self, text: str, *, cues: list[str]) -> AudioAsset:
        digest = sha1(f"{text}|{cues}".encode()).hexdigest()[:12]
        playback_url = f"fake-tts://{digest}"
        return AudioAsset(
            asset_id=playback_url,
            asset_type=AudioAssetType.NARRATION,
            provider="fake-tts",
            playback_url=playback_url,
            duration=max(8, len(text) // 6),
            metadata={"cues": list(cues)},
        )


class MockAudioProvider:
    """Deterministic local audio-source provider; no network or paid API calls."""

    _music_durations = {
        "mock:opening": 22,
        "mock:bridge": 24,
        "mock:resolution": 26,
        "mock:finale": 25,
    }

    def __init__(self, base_url: str = "/api/audio/mock") -> None:
        self.base_url = base_url.rstrip("/")

    def music_source(self, track_ref: str) -> AudioSource:
        duration = self._music_durations.get(track_ref, 30)
        encoded_ref = quote(track_ref, safe="")
        return AudioSource(
            source_url=f"{self.base_url}/music/{encoded_ref}?duration={duration}",
            duration_seconds=duration,
        )

    def narration_source(
        self, segment_id: str, narration_text: str, duration_seconds: int
    ) -> AudioSource:
        del narration_text
        encoded_id = quote(segment_id, safe="")
        return AudioSource(
            source_url=f"{self.base_url}/narration/{encoded_id}?duration={duration_seconds}",
            duration_seconds=duration_seconds,
        )


class FakeMusicProvider:
    def __init__(self) -> None:
        self._tracks = {
            "mock:opening": TrackMetadata(
                track_ref="mock:opening",
                title="Neon First Light",
                artist="Mira Fields",
                duration_seconds=22,
                playable=True,
            ),
            "mock:bridge": TrackMetadata(
                track_ref="mock:bridge",
                title="Midnight Transfer",
                artist="Signal Garden",
                duration_seconds=24,
                playable=True,
            ),
            "mock:resolution": TrackMetadata(
                track_ref="mock:resolution",
                title="Daybreak in Stereo",
                artist="Southbound FM",
                duration_seconds=26,
                playable=True,
            ),
            "mock:finale": TrackMetadata(
                track_ref="mock:finale",
                title="Afterimage Avenue",
                artist="Southbound FM",
                duration_seconds=25,
                playable=True,
            ),
        }

    async def search(self, query: str, *, limit: int = 5) -> list[TrackMetadata]:
        del limit
        return [
            track
            for track in self._tracks.values()
            if query.lower() in f"{track.title} {track.artist}".lower()
        ]

    async def resolve_track(self, track_ref: str) -> TrackMetadata:
        return self._tracks[track_ref]

    async def get_stream_source(self, track_ref: str) -> str:
        await self.resolve_track(track_ref)
        return f"fake-music://{track_ref}"

    async def resolve_track_proposal(self, proposal: object) -> object | None:
        artist = getattr(proposal, "artist", "").casefold()
        title = getattr(proposal, "title", "").casefold()
        for track in self._tracks.values():
            if track.artist.casefold() == artist and track.title.casefold() == title:
                from wavecast.intelligence.models import ResolvedTrack

                return ResolvedTrack(
                    track_ref=track.track_ref,
                    canonical_artist=track.artist,
                    canonical_title=track.title,
                )
        return None

    async def resolve_proposal(self, proposal: object) -> object | None:
        return await self.resolve_track_proposal(proposal)

    async def get_playback_asset(self, track: object) -> AudioAsset:
        track_ref = getattr(track, "track_ref", "")
        metadata = await self.resolve_track(track_ref)
        playback_url = await self.get_stream_source(track_ref)
        return AudioAsset(
            asset_id=metadata.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider="fake-music",
            playback_url=playback_url,
            duration=metadata.duration_seconds,
            metadata=metadata.model_dump(),
        )

    async def playback_asset(self, track: object) -> AudioAsset:
        return await self.get_playback_asset(track)


class MockMusicProvider(FakeMusicProvider):
    """Credential-free music catalog whose assets are loadable by the local API."""

    def __init__(self, base_url: str = "/api/audio/mock") -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")

    async def get_playback_asset(self, track: object) -> AudioAsset:
        metadata = await self.resolve_track(getattr(track, "track_ref", ""))
        playback_url = f"{self.base_url}/music/{quote(metadata.track_ref, safe='')}?duration={metadata.duration_seconds}"
        return AudioAsset(
            asset_id=metadata.track_ref,
            asset_type=AudioAssetType.MUSIC,
            provider="mock-music",
            playback_url=playback_url,
            duration=metadata.duration_seconds,
            metadata=metadata.model_dump(),
        )

    async def playback_asset(self, track: object) -> AudioAsset:
        return await self.get_playback_asset(track)


class FakeCoverRenderer:
    def render_svg(self, *, title: str, seed: int, palette: tuple[str, str]) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">'
            f'<rect width="400" height="400" fill="{palette[0]}"/>'
            f'<circle cx="{seed % 400}" cy="180" r="130" fill="{palette[1]}"/>'
            f'<text x="24" y="340" fill="white" font-size="24">{title}</text></svg>'
        )
