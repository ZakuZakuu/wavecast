Protocol helper provenance
==========================

The protocol helper was copied into the historical experiment from ByteDance's
agentkit-samples repository: https://github.com/bytedance/agentkit-samples
Upstream license: Apache License 2.0; the accompanying LICENSE is preserved.
No upstream commit was recorded in the experiment; do not infer one.

This handoff modifies protocols/protocols.py to remove payload/error logging,
remove payload text from exceptions and Message.__str__, and remove the unused
logging import. Wire parsing and framing are unchanged.
call_podcast.py is the WaveCast experiment client; the global logging disable
was removed because the archived helper no longer logs payloads.
source-hashes.json identifies the pre-modification local experiment files.
This notice is a provenance note, not a claim that an upstream NOTICE file existed.
