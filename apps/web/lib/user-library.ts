import type { LiveEpisode } from "./types";

export type RecentProgramRecord = {
  episodeId: string;
  seedId: string;
  title: string;
  topic: string | null;
  currentTitle: string | null;
  updatedAt: number;
  progressSeconds: number;
  durationSeconds: number;
};

export type SavedEpisodeRecord = RecentProgramRecord & {
  savedAt: number;
};

export type UserLibraryState = {
  version: 1;
  favoriteSeedIds: string[];
  recentPrograms: RecentProgramRecord[];
  savedEpisodes: SavedEpisodeRecord[];
};

const STORAGE_KEY = "wavecast-user-library-v1";
const CHANGE_EVENT = "wavecast-library-change";
const MAX_RECENT = 20;

export const emptyUserLibrary = (): UserLibraryState => ({
  version: 1,
  favoriteSeedIds: [],
  recentPrograms: [],
  savedEpisodes: [],
});

function uniqueStrings(values: unknown): string[] {
  if (!Array.isArray(values)) return [];
  return Array.from(new Set(values.filter((value): value is string => typeof value === "string" && value.length > 0)));
}

function isRecentRecord(value: unknown): value is RecentProgramRecord {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<RecentProgramRecord>;
  return typeof candidate.episodeId === "string"
    && typeof candidate.seedId === "string"
    && typeof candidate.title === "string"
    && (typeof candidate.topic === "string" || candidate.topic === null)
    && (typeof candidate.currentTitle === "string" || candidate.currentTitle === null)
    && typeof candidate.updatedAt === "number"
    && typeof candidate.progressSeconds === "number"
    && typeof candidate.durationSeconds === "number";
}

function isSavedRecord(value: unknown): value is SavedEpisodeRecord {
  return isRecentRecord(value)
    && typeof (value as Partial<SavedEpisodeRecord>).savedAt === "number";
}

export function normalizeUserLibrary(value: unknown): UserLibraryState {
  if (!value || typeof value !== "object") return emptyUserLibrary();
  const candidate = value as Partial<UserLibraryState>;
  return {
    version: 1,
    favoriteSeedIds: uniqueStrings(candidate.favoriteSeedIds),
    recentPrograms: Array.isArray(candidate.recentPrograms)
      ? candidate.recentPrograms.filter(isRecentRecord).slice(0, MAX_RECENT)
      : [],
    savedEpisodes: Array.isArray(candidate.savedEpisodes)
      ? candidate.savedEpisodes.filter(isSavedRecord)
      : [],
  };
}

export function toggleFavoriteInState(state: UserLibraryState, seedId: string): UserLibraryState {
  const exists = state.favoriteSeedIds.includes(seedId);
  return {
    ...state,
    favoriteSeedIds: exists
      ? state.favoriteSeedIds.filter((id) => id !== seedId)
      : [seedId, ...state.favoriteSeedIds],
  };
}

export function upsertRecentInState(
  state: UserLibraryState,
  record: RecentProgramRecord,
): UserLibraryState {
  return {
    ...state,
    recentPrograms: [
      record,
      ...state.recentPrograms.filter((item) => item.episodeId !== record.episodeId),
    ].slice(0, MAX_RECENT),
  };
}

export function upsertSavedInState(
  state: UserLibraryState,
  record: SavedEpisodeRecord,
): UserLibraryState {
  return {
    ...state,
    savedEpisodes: [
      record,
      ...state.savedEpisodes.filter((item) => item.episodeId !== record.episodeId),
    ],
  };
}

export function removeSavedFromState(
  state: UserLibraryState,
  episodeId: string,
): UserLibraryState {
  return {
    ...state,
    savedEpisodes: state.savedEpisodes.filter((item) => item.episodeId !== episodeId),
  };
}

function browserStorage(): Storage | null {
  return typeof window === "undefined" ? null : window.localStorage;
}

export function readUserLibrary(storage: Storage | null = browserStorage()): UserLibraryState {
  if (!storage) return emptyUserLibrary();
  try {
    const raw = storage.getItem(STORAGE_KEY);
    return raw ? normalizeUserLibrary(JSON.parse(raw)) : emptyUserLibrary();
  } catch {
    return emptyUserLibrary();
  }
}

function persistUserLibrary(state: UserLibraryState): UserLibraryState {
  const storage = browserStorage();
  if (!storage) return state;
  storage.setItem(STORAGE_KEY, JSON.stringify(state));
  window.dispatchEvent(new Event(CHANGE_EVENT));
  return state;
}

export function subscribeUserLibrary(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) listener();
  };
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function toggleFavoriteSeed(seedId: string): boolean {
  const next = toggleFavoriteInState(readUserLibrary(), seedId);
  persistUserLibrary(next);
  return next.favoriteSeedIds.includes(seedId);
}

export function isFavoriteSeed(seedId: string): boolean {
  return readUserLibrary().favoriteSeedIds.includes(seedId);
}

export function recentRecordFromEpisode(
  episode: LiveEpisode,
  currentTitle: string | null = null,
  timestamp = Date.now(),
): RecentProgramRecord {
  return {
    episodeId: episode.id,
    seedId: episode.seed_id,
    title: episode.title ?? "WaveCast 节目",
    topic: episode.topic ?? null,
    currentTitle,
    updatedAt: timestamp,
    progressSeconds: Math.max(0, episode.playback_position_seconds),
    durationSeconds: Math.max(
      episode.timeline_duration_seconds,
      episode.program_estimated_duration_seconds,
    ),
  };
}

export function recordRecentEpisode(
  episode: LiveEpisode,
  currentTitle: string | null = null,
): UserLibraryState {
  return persistUserLibrary(
    upsertRecentInState(
      readUserLibrary(),
      recentRecordFromEpisode(episode, currentTitle),
    ),
  );
}

export function saveMaterializedEpisode(
  episode: LiveEpisode,
  currentTitle: string | null = null,
): boolean {
  if (episode.state !== "MATERIALIZED") return false;
  const recent = recentRecordFromEpisode(episode, currentTitle);
  persistUserLibrary(
    upsertSavedInState(
      upsertRecentInState(readUserLibrary(), recent),
      { ...recent, savedAt: Date.now() },
    ),
  );
  return true;
}

export function removeSavedEpisode(episodeId: string): void {
  persistUserLibrary(removeSavedFromState(readUserLibrary(), episodeId));
}

export function isEpisodeSaved(episodeId: string): boolean {
  return readUserLibrary().savedEpisodes.some((item) => item.episodeId === episodeId);
}
