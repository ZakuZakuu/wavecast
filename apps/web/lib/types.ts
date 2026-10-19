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
  /** Short cover label from the backend; absent on programmes made before it existed. */
  cover_title?: string | null;
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

/** What a programme link shows anyone who opens it (never the listener's prompt). */
export type PublicProgramme = {
  id: string;
  title: string;
  cover_title: string | null;
  description: string;
  estimated_duration_seconds: number;
  station: "casual" | "crate" | "portrait" | "lineage" | "night" | null;
  /** Empty for built-in programmes, which have no real outline. */
  route: string[];
  tags: string[];
  opening_track_title: string;
  opening_track_artist: string;
  is_owner: boolean;
  /** A published programme: listeners play the programme itself, nothing is made for them. */
  published?: boolean;
  /** The author has stopped sharing it; only people who already hold a copy can still open it. */
  revoked?: boolean;
};

/** One card of 「大家都在听」: what it shows, nothing about who made it or who listened. */
export type PublicShelfItem = {
  id: string;
  title: string;
  cover_title: string | null;
  station: "casual" | "crate" | "portrait" | "lineage" | "night" | null;
  estimated_duration_seconds: number;
};
export type PublicShelfPage = {
  /** Empty on a first page: too few public programmes, the section is left out. */
  items: PublicShelfItem[];
  /** Asking again with these as `shown` could offer more. */
  has_more: boolean;
};

/** Where the publication of one of the listener's own programmes stands. */
export type PublicationStatus = "preparing" | "mixing" | "published" | "revoked" | "failed";
export type Visibility = "link" | "public";
export type PublicationItem = {
  id: string;
  /** The ten digits of the short link (/p/<code>). */
  code: string;
  episode_id: string;
  status: PublicationStatus;
  visibility: Visibility;
  /** The step being worked on: making the 完整版, mixing it, or nothing more to do. */
  step: "full" | "mix" | "done";
  progress: number;
  error_code?: string | null;
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
  /** The album artwork the catalog lists for the recording (https); absent for older programmes. */
  cover_url?: string | null;
};

export type NarrationSegment = SegmentBase & {
  kind: "NARRATION";
  track_ref: null;
  artist: null;
  narration_role?: "INTRO" | "TRACK_INTRO" | "TRANSITION" | "OUTRO" | "GENERAL";
  hosting_role?: "opening" | "closing" | null;
  /** Short heading of the passage for the route, when the writer supplied one. */
  display_title?: string | null;
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

/** Where the 完整版 (the whole episode, prepared in the background) of an episode stands. */
export type FullVersionState = "none" | "preparing" | "ready" | "failed";
export type FullVersionItem = {
  episode_id: string;
  programme_id: string;
  status: FullVersionState;
  /** 0–100, estimated from the audio finished so far. */
  progress: number;
};

/** A 完整版 asked for from the tuner: the server is still making the programme, or has, or could not. */
export type FullVersionRequestItem = {
  request_id: string;
  status: "creating" | "ready" | "failed";
  episode_id: string | null;
  programme_id: string | null;
  title: string | null;
  message: string | null;
};

export type LiveEpisode = {
  id: string;
  seed_id: string;
  title?: string | null;
  cover_title?: string | null;
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
  /** Artists the listener pressed 少放这类 on, newest first; not part of the onboarding form. */
  avoid_artists?: string[];
  updated_at: string;
};

export type UserPreferencesUpdate = Omit<UserPreferences, "user_id" | "updated_at" | "avoid_artists">;
export type UserEventType = "PLAY_START" | "PLAY_COMPLETE" | "LIKE" | "FAVORITE" | "SAVE" | "SKIP";
export type UserEventInput = { event_type: UserEventType; program_id?: string; episode_id?: string };
export type ProgramIdea = {
  id: string;
  title: string;
  cover_title?: string | null;
  description: string;
  reason: string;
  tags: string[];
  /** The station the backend chose for this idea; absent on ideas made before stations were chosen. */
  station?: string | null;
  source: string;
  status: "AVAILABLE" | "DISMISSED" | "USED";
  created_at: string;
};
