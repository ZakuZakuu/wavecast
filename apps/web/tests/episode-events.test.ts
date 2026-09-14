import { describe, expect, it, vi } from "vitest";

import { applyEpisodeUpdate, subscribeToEpisodeEvents } from "../lib/episode-events";
import type { LiveEpisode } from "../lib/types";

const episode = { id: "episode", version: 2 } as unknown as LiveEpisode;

describe("episode SSE subscription", () => {
  it("applies only newer server snapshots and closes the EventSource", () => {
    const listeners = new Map<string, (event: MessageEvent<string>) => void>();
    const closeSpy = vi.fn();
    vi.stubGlobal("EventSource", class { addEventListener = (name: string, callback: (event: MessageEvent<string>) => void) => listeners.set(name, callback); close = closeSpy; });
    const received: LiveEpisode[] = [];
    const unsubscribe = subscribeToEpisodeEvents("episode", (incoming) => received.push(incoming));

    listeners.get("episode_state_changed")?.({ data: JSON.stringify(episode) } as MessageEvent<string>);
    unsubscribe();

    expect(received[0].version).toBe(2);
    expect(closeSpy).toHaveBeenCalledOnce();
    expect(applyEpisodeUpdate(episode, { ...episode, version: 1 })).toBe(episode);
    expect(applyEpisodeUpdate(episode, { ...episode, version: 3 }).version).toBe(3);
  });
});
