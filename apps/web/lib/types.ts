export type SegmentKind = "MUSIC" | "NARRATION";
export type SegmentState = "PLANNED" | "SCRIPT_READY" | "AUDIO_GENERATING" | "AUDIO_READY" | "COMMITTED" | "PLAYED" | "SKIPPED";

export type DurationIntent = "AUTO" | "SHORT" | "STANDARD" | "DEEP";
export type HostMode = "NONE" | "LIGHT" | "FULL";
export type OpeningStrategy = "FULL_TRACK" | "OPPORTUNISTIC" | "EARLY_BRIDGE";
export type TransitionStyle = "CLEAN" | "RADIO" | "DJ";
export type PresentationIntent = {
  host_mode: HostMode;
  opening_strategy: OpeningStrategy;
  transition_style: TransitionStyle;
};

export type Seed = {
  id: string;
  title: string;
  topic: string;
  short_description: string;
  estimated_duration_seconds: number;
  opening_track_ref: string;
  opening_track_title: string;
  opening_track_artist: string;
  opening_narration_text?: string | null;
  cover: { family: string; seed: number; palette: [string, string] };
  presentation_intent?: PresentationIntent;
};

export type ProgramProposal = Seed & {
  editorial_route: string[];
  genre_tags: string[];
  mood_tags: string[];
  anchor_artists: string[];
  generation_profile: string;
  created_at: string;
};

export type ProgramProposalBatch = {
  proposals: ProgramProposal[];
};

export type ProposalGenerationRequest = {
  prompt: string;
  duration_intent: DurationIntent;
  count?: number;
  /** Optional listener taste summary; accepted by the backend (≤1000 chars). */
  taste_context?: string;
  /** Spoken language of the programme; omitted lets the backend guess from the request text. */
  output_language?: "zh-CN" | "en-US" | "ja-JP";
  /** The station the listener tuned: sets the default hosting (夜里 means no host). */
  station?: "casual" | "crate" | "portrait" | "lineage" | "night";
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

export type ProgramRenderChunk = {
  index: number;
  startSeconds: number;
  durationSeconds: number;
  planFingerprint: string;
  contentSha256: string;
  assetKey: string;
  audioUrl: string;
};

export type ProgramRenderManifest = {
  schemaVersion: 1;
  episodeId: string;
  revision: string;
  chunkDurationSeconds: number;
  holdbackSeconds: number;
  renderedFrontierSeconds: number;
  complete: boolean;
  chunks: ProgramRenderChunk[];
  streamUrl: string;
};

export type SourceNotice = { kind: "UNPLAYABLE_ARTISTS"; artists: string[] };

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
  program_playback_position_seconds?: number;
  /** Server activity timestamp (ISO); bumped by playback checkpoints. */
  last_activity_at?: string;
  program_transport_active?: boolean;
  program_rendered_frontier_seconds?: number | null;
  program_publication_latency_seconds?: number;
  is_listener_active: boolean;
  is_playing: boolean;
  program_estimated_duration_seconds: number;
  presentation_intent?: PresentationIntent;
  generated_frontier_seconds: number;
  buffer_ahead_seconds: number;
  committed_frontier_seconds: number;
  timeline_duration_seconds: number;
  /** Present when the route cannot play artists the listener asked for. */
  source_notice?: SourceNotice | null;
};

export type UserGenre =
  | "City Pop"
  | "R&B"
  | "Jazz"
  | "Electronic"
  | "Hip-Hop"
  | "Rock"
  | "Classical";
export type UserMood = "Chill" | "Focus" | "Late Night" | "Discovery";
export type DiscoveryLevel = "SAFE" | "BALANCED" | "ADVENTUROUS";

export type UserPreferences = {
  user_id: string;
  genres: UserGenre[];
  artists: string[];
  moods: UserMood[];
  contexts: string[];
  discovery_level: DiscoveryLevel;
  onboarding_completed: boolean;
  updated_at: string;
};

export type UserPreferencesUpdate = Omit<UserPreferences, "user_id" | "updated_at">;
export type UserEventType = "PLAY_START" | "PLAY_COMPLETE" | "LIKE" | "FAVORITE" | "SAVE" | "SKIP";
export type UserEventInput = { event_type: UserEventType; program_id?: string; episode_id?: string };
export type ProgramIdea = {
  id: string;
  title: string;
  description: string;
  reason: string;
  tags: string[];
  source: string;
  status: "AVAILABLE" | "DISMISSED" | "USED";
  created_at: string;
};
