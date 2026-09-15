export type SegmentKind = "MUSIC" | "NARRATION";
export type SegmentState = "PLANNED" | "SCRIPT_READY" | "AUDIO_GENERATING" | "AUDIO_READY" | "COMMITTED" | "PLAYED" | "SKIPPED";

export type Seed = {
  id: string;
  title: string;
  topic: string;
  short_description: string;
  estimated_duration_seconds: number;
  opening_track_ref: string;
  opening_track_title: string;
  opening_track_artist: string;
  cover: { family: string; seed: number; palette: [string, string] };
};

export type Segment = {
  id: string;
  chapter_id: string;
  order: number;
  kind: SegmentKind;
  state: SegmentState;
  planned_duration_seconds: number;
  actual_duration_seconds: number | null;
  track_ref: string | null;
  title: string;
  artist: string | null;
  narration_text: string | null;
  asset_ref: string | null;
};

export type LiveEpisode = {
  id: string;
  seed_id: string;
  listener_id: string;
  version: number;
  state: "STREAMING" | "MATERIALIZING" | "MATERIALIZED" | string;
  generation_mode: "PROGRESSIVE" | "FULL";
  segments: Segment[];
  current_segment_id: string | null;
  playback_position_seconds: number;
  is_listener_active: boolean;
  is_playing: boolean;
  program_estimated_duration_seconds: number;
  generated_frontier_seconds: number;
  committed_frontier_seconds: number;
  timeline_duration_seconds: number;
};
