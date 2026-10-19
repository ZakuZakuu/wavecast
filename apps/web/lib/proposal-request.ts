import { lessLikeThisArtists } from "./listener-feedback";
import type { Station } from "./stations";
import { readLocalTaste, tasteContext } from "./taste";
import type { DurationIntent, HostMode } from "./types";

/** Spoken language of generated programmes; follows the (Chinese-only) interface language. */
export const PROGRAMME_LANGUAGE = "zh-CN" as const;

/**
 * What the tuner asks the server for: the station's default topic when nothing was typed. `hostMode` is
 * only passed when the listener chose it with the host control; left out, the station's own default stands.
 */
export function proposalRequest(target: Station, prompt: string, duration: DurationIntent, hostMode?: HostMode | null) {
  return {
    prompt: prompt.trim().length >= 2 ? prompt.trim() : target.defaultTopic,
    duration_intent: duration,
    taste_context: tasteContext(readLocalTaste(), lessLikeThisArtists()),
    // The interface is Chinese: the programme follows it, not the language of the keyword.
    output_language: PROGRAMME_LANGUAGE,
    station: target.id,
    ...(hostMode ? { host_mode: hostMode } : {}),
  };
}
