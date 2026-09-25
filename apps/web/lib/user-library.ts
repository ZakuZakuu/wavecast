import type { LiveEpisode } from "./types";
import { api } from "./api";
import { getApiAuthUserId } from "./auth-client";

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
  createdProgramIds: string[];
};

const STORAGE_KEY = "wavecast-user-library-v1";
const CHANGE_EVENT = "wavecast-library-change";
const MAX_RECENT = 20;
const GUEST_MERGED_SUFFIX = ":guest-merged-v1";
let activeAccountId: string | null = null;

function accountStorageKey(userId: string): string {
  return `${STORAGE_KEY}:account:${encodeURIComponent(userId)}`;
}

function guestMergedMarker(userId: string): string {
  return accountStorageKey(userId) + GUEST_MERGED_SUFFIX;
}

export const emptyUserLibrary = (): UserLibraryState => ({
  version: 1,
  favoriteSeedIds: [],
  recentPrograms: [],
  savedEpisodes: [],
  createdProgramIds: [],
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
    createdProgramIds: uniqueStrings(candidate.createdProgramIds),
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

function readStorageKey(storage: Storage | null, key: string): UserLibraryState {
  if (!storage) return emptyUserLibrary();
  try {
    const raw = storage.getItem(key);
    return raw ? normalizeUserLibrary(JSON.parse(raw)) : emptyUserLibrary();
  } catch {
    return emptyUserLibrary();
  }
}

export function readUserLibrary(storage: Storage | null = browserStorage()): UserLibraryState {
  const key = storage && storage !== browserStorage()
    ? STORAGE_KEY
    : activeAccountId ? accountStorageKey(activeAccountId) : STORAGE_KEY;
  return readStorageKey(storage, key);
}

function persistUserLibrary(state: UserLibraryState): UserLibraryState {
  const storage = browserStorage();
  if (!storage) return state;
  const key = activeAccountId ? accountStorageKey(activeAccountId) : STORAGE_KEY;
  storage.setItem(key, JSON.stringify(state));
  window.dispatchEvent(new Event(CHANGE_EVENT));
  return state;
}

export function useGuestLibraryIdentity(): void {
  activeAccountId = null;
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGE_EVENT));
}

function mergeLocalLibraries(
  left: UserLibraryState,
  right: UserLibraryState,
): UserLibraryState {
  const recents = new Map<string, RecentProgramRecord>();
  for (const item of [...left.recentPrograms, ...right.recentPrograms]) {
    const existing = recents.get(item.episodeId);
    if (!existing || item.updatedAt >= existing.updatedAt) recents.set(item.episodeId, item);
  }
  const saved = new Map<string, SavedEpisodeRecord>();
  for (const item of [...left.savedEpisodes, ...right.savedEpisodes]) {
    const existing = saved.get(item.episodeId);
    if (!existing || item.savedAt >= existing.savedAt) saved.set(item.episodeId, item);
  }
  return normalizeUserLibrary({
    version: 1,
    favoriteSeedIds: [...left.favoriteSeedIds, ...right.favoriteSeedIds],
    recentPrograms: [...recents.values()].sort((a, b) => b.updatedAt - a.updatedAt),
    savedEpisodes: [...saved.values()].sort((a, b) => b.savedAt - a.savedAt),
    createdProgramIds: [...left.createdProgramIds, ...right.createdProgramIds],
  });
}

export async function syncAuthenticatedLibrary(): Promise<UserLibraryState> {
  const userId = await getApiAuthUserId();
  if (!userId) return readUserLibrary();
  const storage = browserStorage();
  const accountCache = readStorageKey(storage, accountStorageKey(userId));
  const guestCache = readStorageKey(storage, STORAGE_KEY);
  const markerKey = guestMergedMarker(userId);
  const shouldMergeGuest = storage?.getItem(markerKey) !== "1";
  const pendingMerge = shouldMergeGuest
    ? mergeLocalLibraries(accountCache, guestCache)
    : accountCache;
  activeAccountId = userId;
  try {
    if (shouldMergeGuest) {
      await api.mergeMyLibrary(pendingMerge);
      storage?.setItem(markerKey, "1");
    }
    const canonical = normalizeUserLibrary(await api.myLibrary());
    return persistUserLibrary(canonical);
  } catch (error) {
    // Keep both caches intact; the account-scoped cache remains isolated from other users.
    persistUserLibrary(pendingMerge);
    throw error;
  }
}

export function subscribeUserLibrary(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY || event.key?.startsWith(`${STORAGE_KEY}:account:`)) listener();
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
  if (activeAccountId) {
    const enabled = next.favoriteSeedIds.includes(seedId);
    void api.favoriteProgram(seedId, enabled)
      .then((value) => persistUserLibrary(normalizeUserLibrary(value)))
      .catch(() => undefined);
  }
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
  const next = persistUserLibrary(
    upsertRecentInState(
      readUserLibrary(),
      recentRecordFromEpisode(episode, currentTitle),
    ),
  );
  if (activeAccountId) {
    const record = recentRecordFromEpisode(episode, currentTitle);
    void api.recordLibraryRecent(record)
      .then((value) => persistUserLibrary(normalizeUserLibrary(value)))
      .catch(() => undefined);
  }
  return next;
}

export function saveMaterializedEpisode(
  episode: LiveEpisode,
  currentTitle: string | null = null,
): boolean {
  if (episode.state !== "MATERIALIZED") return false;
  const recent = recentRecordFromEpisode(episode, currentTitle);
  const saved = { ...recent, savedAt: Date.now() };
  persistUserLibrary(
    upsertSavedInState(
      upsertRecentInState(readUserLibrary(), recent),
      saved,
    ),
  );
  if (activeAccountId) {
    void api.saveLibraryEpisode(saved)
      .then((value) => persistUserLibrary(normalizeUserLibrary(value)))
      .catch(() => undefined);
  }
  return true;
}

export function removeSavedEpisode(episodeId: string): void {
  persistUserLibrary(removeSavedFromState(readUserLibrary(), episodeId));
  if (activeAccountId) {
    void api.removeLibraryEpisode(episodeId)
      .then((value) => persistUserLibrary(normalizeUserLibrary(value)))
      .catch(() => undefined);
  }
}

export function isEpisodeSaved(episodeId: string): boolean {
  return readUserLibrary().savedEpisodes.some((item) => item.episodeId === episodeId);
}


export function recordCreatedProgram(programId: string): UserLibraryState {
  const current = readUserLibrary();
  return persistUserLibrary({
    ...current,
    createdProgramIds: [
      programId,
      ...current.createdProgramIds.filter((id) => id !== programId),
    ],
  });
}
