import { parseMixPlan, type MixPlan } from "./mix-timeline";
import type {
  UserEventInput,
  UserEventType,
  UserPreferences,
  UserPreferencesUpdate,
  ProgramIdea,
  LiveEpisode,
  ProgramProposal,
  ProgramProposalBatch,
  ProposalGenerationRequest,
  Seed,
} from "./types";
import type { MixdownArtifact, MixdownPreparationResult } from "./episode-export";
import { getApiAuthToken, getApiAuthTokenForUser } from "./auth-client";

const listenerStorageKey = "wavecast-anonymous-listener";

function listenerId(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const existing = window.localStorage.getItem(listenerStorageKey);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.localStorage.setItem(listenerStorageKey, created);
  return created;
}

async function request<T>(
  path: string,
  init?: RequestInit,
  expectedUserId?: string,
): Promise<T> {
  const anonymousListener = listenerId();
  const bearerToken = expectedUserId
    ? await getApiAuthTokenForUser(expectedUserId)
    : await getApiAuthToken();
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(anonymousListener ? { "X-Wavecast-Listener": anonymousListener } : {}),
      ...(bearerToken ? { Authorization: `Bearer ${bearerToken}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "Request failed");
  return response.json() as Promise<T>;
}

export const api = {
  seeds: () => request<Seed[]>("/seeds"),
  program: (id: string) => request<ProgramProposal>(`/programs/${id}`),
  userPreferences: () => request<UserPreferences>("/user-preferences/me"),
  saveUserPreferences: (input: UserPreferencesUpdate) =>
    request<UserPreferences>("/user-preferences/me", {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  deleteUserPreferences: () => request<UserPreferences>("/user-preferences/me", { method: "DELETE" }),
  createUserEvent: (input: UserEventInput) =>
    request<{ id: string; event_type: UserEventType }>("/user-events", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  recordUserEvent: async (input: UserEventInput) => {
    if (!(await getApiAuthToken())) return;
    await request<{ id: string; event_type: UserEventType }>("/user-events", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  recommendations: (expectedUserId: string) =>
    request<ProgramIdea[]>("/recommendations/me", undefined, expectedUserId),
  refreshRecommendations: (expectedUserId: string) =>
    request<ProgramIdea[]>(
      "/recommendations/me/refresh",
      { method: "POST" },
      expectedUserId,
    ),
  materializeRecommendation: (id: string, expectedUserId: string) =>
    request<ProgramProposalBatch>(
      `/recommendations/me/${encodeURIComponent(id)}/program-proposal`,
      { method: "POST" },
      expectedUserId,
    ),
  createProgramProposals: (input: ProposalGenerationRequest) =>
    request<ProgramProposalBatch>("/program-proposals", {
      method: "POST",
      body: JSON.stringify({ ...input, count: input.count ?? 1 }),
    }),
  start: (seedId: string) => request<LiveEpisode>(`/episodes/from-seed/${seedId}`, { method: "POST" }),
  get: (id: string) => request<LiveEpisode>(`/episodes/${id}`),
  mixPlan: async (id: string): Promise<MixPlan> => parseMixPlan(await request<unknown>(`/episodes/${id}/mix-plan`)),
  ensureBuffer: (id: string, targetChapters = 2) => request<LiveEpisode>(`/episodes/${id}/ensure-buffer`, { method: "POST", body: JSON.stringify({ target_chapters: targetChapters }) }),
  completed: (id: string) => request<LiveEpisode>(`/episodes/${id}/completed`, { method: "POST" }),
  heartbeat: (id: string) => request<LiveEpisode>(`/episodes/${id}/heartbeat`, { method: "POST" }),
  commit: (id: string, segmentId: string) => request<LiveEpisode>(`/episodes/${id}/commit/${segmentId}`, { method: "POST" }),
  next: (id: string) => request<LiveEpisode>(`/episodes/${id}/next`, { method: "POST" }),
  seek: (id: string, position: number) => request<LiveEpisode>(`/episodes/${id}/seek`, { method: "POST", body: JSON.stringify({ position_seconds: position }) }),
  checkpoint: (id: string, position: number) => request<LiveEpisode>(`/episodes/${id}/playback-checkpoint`, { method: "POST", body: JSON.stringify({ position_seconds: position }) }),
  leave: (id: string) => request<LiveEpisode>(`/episodes/${id}/leave`, { method: "POST" }),
  pause: (id: string) => request<LiveEpisode>(`/episodes/${id}/pause`, { method: "POST" }),
  resume: (id: string) => request<LiveEpisode>(`/episodes/${id}/resume`, { method: "POST" }),
  materialize: (id: string) => request<LiveEpisode>(`/episodes/${id}/materialize`, { method: "POST" }),
  prepareMixdown: (id: string) => request<MixdownPreparationResult>(`/episodes/${id}/prepare-mixdown`, { method: "POST" }),
  mixdown: (id: string) => request<MixdownArtifact>(`/episodes/${id}/mixdown`, { method: "POST" }),
  myLibrary: (expectedUserId: string) => request<unknown>("/me/library", undefined, expectedUserId),
  mergeMyLibrary: (library: unknown, expectedUserId: string) => request<unknown>("/me/library/merge", {
    method: "POST",
    body: JSON.stringify({ library }),
  }, expectedUserId),
  favoriteProgram: (id: string, favorite: boolean, expectedUserId: string) => request<unknown>(
    `/me/library/favorites/${encodeURIComponent(id)}`,
    { method: favorite ? "PUT" : "DELETE" },
    expectedUserId,
  ),
  recordLibraryRecent: (record: unknown, expectedUserId: string) => {
    const value = record as { episodeId: string };
    return request<unknown>(`/me/library/recents/${encodeURIComponent(value.episodeId)}`, {
      method: "PUT",
      body: JSON.stringify(record),
    }, expectedUserId);
  },
  saveLibraryEpisode: (record: unknown, expectedUserId: string) => {
    const value = record as { episodeId: string };
    return request<unknown>(`/me/library/saved/${encodeURIComponent(value.episodeId)}`, {
      method: "PUT",
      body: JSON.stringify(record),
    }, expectedUserId);
  },
  removeLibraryEpisode: (id: string, expectedUserId: string) => request<unknown>(
    `/me/library/saved/${encodeURIComponent(id)}`,
    { method: "DELETE" },
    expectedUserId,
  ),
};
