"""The chosen Doubao voice combination for two-host passages (configuration only).

Combination B was chosen by the user from the listening samples: the first host speaks with
Liu Fei's voice, the second answers with Xiao Lei's, at speech rate 0.  This module holds the
mapping and nothing else - no adapter, no network.  The ids are the vendor's and live here (and
in the snapshot stored with the audio), never in the dialogue.  Speech rate 0 is on Doubao's own
scale; it is not comparable with MiniMax's 0.9.
"""

from __future__ import annotations

from wavecast.models.dialogue import DialogueSpeaker, VoiceRoleSnapshot

DOUBAO_PROVIDER_NAME = "doubao_podcast"
VOICE_COMBINATION_B: tuple[VoiceRoleSnapshot, ...] = (
    VoiceRoleSnapshot(speaker=DialogueSpeaker.A, voice_id="zh_male_liufei_v2_saturn_bigtts"),
    VoiceRoleSnapshot(speaker=DialogueSpeaker.B, voice_id="zh_male_xiaolei_v2_saturn_bigtts"),
)
SPEECH_RATE_B = 0
