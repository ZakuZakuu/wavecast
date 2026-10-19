import { lessLikeThisArtists } from "./listener-feedback";
import type { Station } from "./stations";
import { readLocalTaste, tasteContext } from "./taste";
import type { DurationIntent } from "./types";

/** Spoken language of generated programmes; follows the (Chinese-only) interface language. */
export const PROGRAMME_LANGUAGE = "zh-CN" as const;

/** What the tuner asks the server for: the station's default topic when nothing was typed. */
export function proposalRequest(target: Station, prompt: string, duration: DurationIntent) {
  return {
    prompt: prompt.trim().length >= 2 ? prompt.trim() : target.defaultTopic,
    duration_intent: duration,
    taste_context: tasteContext(readLocalTaste(), lessLikeThisArtists()),
    // The interface is Chinese: the programme follows it, not the language of the keyword.
    output_language: PROGRAMME_LANGUAGE,
    station: target.id,
  };
}
