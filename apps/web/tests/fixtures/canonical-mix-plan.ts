import type { MixPlan } from "../../lib/mix-timeline";

export const canonicalPlan: MixPlan = {
  schemaVersion: 1,
  episodeId: "phase6-fixture",
  durationSeconds: 72,
  segmentStarts: { "music-a": 0, "voice-a": 39, "music-b": 37 },
  clips: [
    {
      id: "music-a:music", segmentId: "music-a", sourceUrl: "/a.mp3", lane: "MUSIC",
      timelineStartSeconds: 0, sourceOffsetSeconds: 0, playableDurationSeconds: 40,
      gain: 1, fadeInSeconds: 0, fadeOutSeconds: 3,
      gainAutomation: [
        { offsetSeconds: 0, gain: 1 },
        { offsetSeconds: 37, gain: 1 },
        { offsetSeconds: 38.5, gain: 0.5 },
        { offsetSeconds: 39, gain: 0.1166666667 },
        { offsetSeconds: 40, gain: 0 },
      ],
    },
    {
      id: "voice-a:voice", segmentId: "voice-a", sourceUrl: "/voice-a.mp3", lane: "VOICE",
      timelineStartSeconds: 39, sourceOffsetSeconds: 0, playableDurationSeconds: 8,
      gain: 1, fadeInSeconds: 0.08, fadeOutSeconds: 0.08,
      gainAutomation: [
        { offsetSeconds: 0, gain: 0 },
        { offsetSeconds: 0.08, gain: 1 },
        { offsetSeconds: 7.92, gain: 1 },
        { offsetSeconds: 8, gain: 0 },
      ],
    },
    {
      id: "music-b:music", segmentId: "music-b", sourceUrl: "/b.mp3", lane: "MUSIC",
      timelineStartSeconds: 37, sourceOffsetSeconds: 0, playableDurationSeconds: 35,
      gain: 1, fadeInSeconds: 3, fadeOutSeconds: 0,
      gainAutomation: [
        { offsetSeconds: 0, gain: 0 },
        { offsetSeconds: 1.5, gain: 0.5 },
        { offsetSeconds: 2, gain: 0.2333333333 },
        { offsetSeconds: 10, gain: 0.35 },
        { offsetSeconds: 10.5, gain: 1 },
        { offsetSeconds: 35, gain: 1 },
      ],
    },
  ],
};
