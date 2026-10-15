# Third-party material

`agentkit-samples-LICENSE` is the Apache License 2.0 text of
[bytedance/agentkit-samples](https://github.com/bytedance/agentkit-samples). The frame layout and
event numbers in `backend/wavecast/providers/doubao_frames.py` follow the protocol helper from that
repository as it was used by the successful 2026-10-14 Doubao experiment (see
`docs/research/dialogue-radio-2026-10/doubao-fixed-script-handoff/` on the
`docs/doubao-protocol-review-302` branch). The module is a re-implementation for application use,
not a copy: it has no logging, puts no payload into exceptions, and refuses frames it does not
understand. The upstream commit was not recorded in the experiment and is not claimed here.
