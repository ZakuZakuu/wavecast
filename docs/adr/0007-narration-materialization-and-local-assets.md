# ADR 0007: Provider-backed narration materialization

## Context

Phase 4.2 established structured radio script blocks and a provider-neutral
`TTSProvider`, but the runtime still used synchronous mock `AudioProvider` narration
sources. MiniMax Speech 2.8 HD returns temporary or hex-encoded output, so narration
must be converted into a WaveCast-owned browser asset without putting network I/O in
the deterministic episode orchestrator.

## Decision

`NarrationSegment` preserves provider-neutral `tts_cues` from `RadioScriptBlock`.
`NarrationMaterializer` is an asynchronous service that renders a small semantic cue
allowlist, invokes the existing `TTSProvider`, stores the resulting audio, and moves
segments through `SCRIPT_READY -> AUDIO_GENERATING -> AUDIO_READY`. It resets failed
requests to `SCRIPT_READY` and never regenerates committed, played, or skipped
segments.

`MiniMaxTTSProvider` uses the synchronous `POST /v1/t2a_v2` contract with
`speech-2.8-hd`, `stream=false`, `output_format=hex`, and explicit voice/audio
configuration. It validates `base_resp`, decodes hex bytes, uses the documented
millisecond `extra_info.audio_length` when present, and otherwise derives duration
from MP3 frame headers. API usage is recorded before failures escape.

`LocalObjectStorageProvider` implements the existing asynchronous
`ObjectStorageProvider` seam for development and tests. Its `put()` and `get()`
operations are awaitable so a future R2/S3 adapter can perform network I/O without
blocking the TTS path; `url_for()` remains synchronous deterministic URL
construction. It writes content-addressed files and metadata below
`.wavecast-data/audio`, returns `/api/assets/audio/<key>` URLs, and rejects path
traversal. A per-process keyed lock and the same content-addressed key prevent
duplicate TTS calls for identical provider/model/voice/audio/text/cue inputs.

Cue rendering is versioned (`wavecast-cues-v2`). Positionless pause cues remain in
the cache identity but are not emitted into MiniMax text until the script model
provides safe sentence positions; only the currently safe `breath` cue is rendered.

Provider selection is explicit: mock mode constructs `MockTTSProvider`, while live
mode always constructs `MiniMaxTTSProvider`. Missing live credentials surface a
typed configuration error at materialization rather than silently producing mock
audio. The opt-in `scripts/minimax_tts_probe.py` is the only live smoke harness and
is never run by CI.

Mock mode uses `MockTTSProvider` with the same materializer and local storage path;
`FakeTTSProvider` remains available for isolated contract tests. No MiniMax request is
made without live mode, an API key, and an explicitly configured voice ID.

## Consequences

The browser receives persistent WaveCast-owned audio URLs and actual generated
durations, while playback clock/frontier/version semantics remain unchanged. The
legacy synchronous mock `AudioProvider` path remains available to deterministic
orchestrator unit tests; API full materialization uses the async narration seam.
No streaming TTS, voice cloning, new music provider, queue, or frontend redesign is
introduced.
