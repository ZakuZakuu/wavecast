# Published runway and recoverable audio cache

Status: Accepted for Listening P0, 2026-09-30.

The hosted programme can have generated track metadata while the audio feed
cannot advance. A human test confirmed ENOSPC on the small Railway volume.
HLS-only GC did not cover source snapshots, and failed atomic writes could leak
temporary files. Raw segment duration also overstates the listener's published
runway and excludes download/render latency from refill timing.

Use the successfully published HLS frontier for programme refill signals.
Start with a 300-second trigger to preserve a 180-second safety runway; observed
generation plus publication latency increases the trigger up to 600 seconds.
Keep the existing bounded chapter policy. Already-ready successors awaiting
publication should not cause duplicate music generation. This is scheduling
metadata, not a change to the immutable audio timeline or full-generation mode.

Under storage pressure, reclaim stale unpublished temporary files, inactive HLS
caches, then recoverable inactive music snapshot bytes. Protect current/recently
active listeners' sources and paid narration. Retain source metadata and a
content checksum; pin checksums on legacy source snapshots before eviction.
An evicted owned source restores to the same key only if the safe provider
identity and fetched content checksum match. Never substitute changed audio.
Failed atomic writes remove their temporary file and preserve the previous
published destination. Run collection at startup and before programme rendering;
emit safe pressure/collection metadata at an observable log level.

This keeps the existing MixPlan, progressive generation and FFmpeg transport.
Moving all assets to object storage could remove the volume limit but adds
infrastructure outside the immediate checkpoint. Increasing storage alone would
delay the same leak. Three minutes is a safety target, not a guarantee against
an indefinitely unavailable provider; hosted listening acceptance is still
required before moving to UI P0.
