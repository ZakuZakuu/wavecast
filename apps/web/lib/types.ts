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

type SegmentBase = {
  id: string;
  chapter_id: string;
  order: number;
  state: SegmentState;
  planned_duration_seconds: number;
  actual_duration_seconds: number | null;
  audio_source_url: string | null;
  duration_seconds: number;
  title: string;
  narration_text: string | null;
  /** Optional pronunciation copy; the player/UI continues to show narration_text. */
  tts_text?: string | null;
  asset_ref: string | null;
};

export type MusicSegment = SegmentBase & {
  kind: "MUSIC";
  track_ref: string;
  artist: string | null;
};

export type NarrationSegment = SegmentBase & {
  kind: "NARRATION";
  track_ref: null;
  artist: null;
};

export type Segment = MusicSegment | NarrationSegment;

export type LiveEpisode = {
  id: string;
  seed_id: string;
  title?: string | null;
  topic?: string | null;
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
  buffer_ahead_seconds: number;
  committed_frontier_seconds: number;
  timeline_duration_seconds: number;
};
