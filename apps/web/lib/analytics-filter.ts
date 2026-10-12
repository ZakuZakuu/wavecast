/**
 * What Vercel Web Analytics may send. The home-screen app and the share links
 * carry things that identify a programme, a listener or a station choice, so
 * before an event leaves the browser:
 *  - the query string and the hash are dropped (e.g. ?station=, ?c=);
 *  - the id in a dynamic path is replaced by a placeholder
 *    (/program/<id>, /p/<code>, /episode/<id>, /episode/materialized/<id>);
 *  - nothing is sent from a browser that has switched statistics off.
 * Request text, e-mail, account ids and audio URLs never appear in a page URL,
 * and the analytics script is not given anything else.
 */

export const ANALYTICS_DISABLED_KEY = "wavecast-analytics-disabled";

const DYNAMIC_PATHS: Array<[RegExp, string]> = [
  [/^\/episode\/materialized\/[^/]+/, "/episode/materialized/[episodeId]"],
  [/^\/episode\/[^/]+/, "/episode/[seedId]"],
  [/^\/program\/[^/]+/, "/program/[seedId]"],
  [/^\/p\/[^/]+/, "/p/[code]"],
];

type StorageReader = Pick<Storage, "getItem">;

function browserStorage(): StorageReader | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** True when this browser has opted out (localStorage "wavecast-analytics-disabled" = "true"). */
export function analyticsDisabled(storage: StorageReader | null = browserStorage()): boolean {
  try {
    return storage?.getItem(ANALYTICS_DISABLED_KEY) === "true";
  } catch {
    return false;
  }
}

/** The page URL without query, hash or the ids in dynamic paths. */
export function sanitizeAnalyticsUrl(raw: string): string {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return raw.split(/[?#]/)[0];
  }
  let pathname = url.pathname;
  for (const [pattern, replacement] of DYNAMIC_PATHS) {
    if (pattern.test(pathname)) {
      pathname = pathname.replace(pattern, replacement);
      break;
    }
  }
  return `${url.origin}${pathname}`;
}

/** `beforeSend` for the analytics component: null drops the event. */
export function beforeSendAnalytics<T extends { url: string }>(
  event: T,
  storage: StorageReader | null = browserStorage(),
): T | null {
  if (analyticsDisabled(storage)) return null;
  return { ...event, url: sanitizeAnalyticsUrl(event.url) };
}
