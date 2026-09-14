import type { LiveEpisode, Seed } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "Request failed");
  return response.json() as Promise<T>;
}

export const api = {
  seeds: () => request<Seed[]>("/seeds"),
  start: (seedId: string) => request<LiveEpisode>(`/episodes/from-seed/${seedId}`, { method: "POST" }),
  advance: (id: string) => request<LiveEpisode>(`/episodes/${id}/advance`, { method: "POST" }),
  commit: (id: string, segmentId: string) => request<LiveEpisode>(`/episodes/${id}/commit/${segmentId}`, { method: "POST" }),
  next: (id: string) => request<LiveEpisode>(`/episodes/${id}/next`, { method: "POST" }),
  seek: (id: string, position: number) => request<LiveEpisode>(`/episodes/${id}/seek`, { method: "POST", body: JSON.stringify({ position_seconds: position }) }),
  leave: (id: string) => request<LiveEpisode>(`/episodes/${id}/leave`, { method: "POST" }),
  resume: (id: string) => request<LiveEpisode>(`/episodes/${id}/resume`, { method: "POST" }),
  materialize: (id: string) => request<LiveEpisode>(`/episodes/${id}/materialize`, { method: "POST" }),
};
