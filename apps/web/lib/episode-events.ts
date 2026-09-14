import type { LiveEpisode } from "./types";

export function applyEpisodeUpdate(current: LiveEpisode | null, incoming: LiveEpisode): LiveEpisode {
  return !current || incoming.version > current.version ? incoming : current;
}

export function subscribeToEpisodeEvents(
  episodeId: string,
  onEpisode: (episode: LiveEpisode) => void,
): () => void {
  const source = new EventSource(`/api/episodes/${episodeId}/events`);
  source.addEventListener("episode_state_changed", (event) => {
    onEpisode(JSON.parse((event as MessageEvent<string>).data) as LiveEpisode);
  });
  return () => source.close();
}
