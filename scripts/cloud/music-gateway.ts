// One-file Railway Function. No credentials or playback URLs are logged.
import { timingSafeEqual } from "node:crypto";

type Env = Record<string, string | undefined>;
type Options = { fetcher?: typeof fetch; now?: () => number; maxRequests?: number; maxConcurrent?: number };

export function makeGateway(env: Env, options: Options = {}) {
  const fetcher = options.fetcher ?? fetch;
  const now = options.now ?? Date.now;
  const token = env.MUSIC_GATEWAY_TOKEN ?? "";
  const expected = Buffer.from(`Bearer ${token}`);
  let origin: URL | undefined;
  try {
    const parsed = new URL(env.MUSIC_SIDECAR_URL ?? "");
    if (parsed.protocol === "http:" && parsed.hostname === "music-sidecar.railway.internal"
        && !parsed.username && !parsed.password && parsed.pathname === "/"
        && !parsed.search && !parsed.hash) origin = parsed;
  } catch { /* Missing configuration fails closed. */ }
  const configured = token.length >= 32 && !!origin;
  const maxRequests = options.maxRequests ?? 120;
  const maxConcurrent = options.maxConcurrent ?? 3;
  let windowStart = now(), count = 0, active = 0;
  const json = (value: object, status = 200, extra: Record<string, string> = {}) =>
    Response.json(value, { status, headers: { "Cache-Control": "no-store", ...extra } });

  return async function handle(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET")
      return json({ status: configured ? "ok" : "not configured" }, configured ? 200 : 503);
    if (!configured) return json({ detail: "gateway unavailable" }, 503);
    const supplied = Buffer.from(request.headers.get("Authorization") ?? "");
    if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected))
      return json({ detail: "unauthorized" }, 401);
    if (request.method !== "GET") return json({ detail: "method not allowed" }, 405, { Allow: "GET" });
    if (url.pathname === "/search") {
      const params = url.searchParams;
      const query = params.get("query") ?? "";
      const limit = params.get("limit") ?? "5";
      if (query.trim().length === 0 || query.length > 300 || !/^\d+$/.test(limit)
          || Number(limit) < 1 || Number(limit) > 50
          || [...params.keys()].some(k => !["query", "limit"].includes(k))
          || params.getAll("query").length !== 1 || params.getAll("limit").length > 1)
        return json({ detail: "invalid search" }, 400);
    } else if ((url.pathname !== "/ready" && !/^\/tracks\/\d{1,20}(\/(timing|playback))?$/.test(url.pathname))
        || url.search) return json({ detail: "route not allowed" }, 404);
    if (now() - windowStart >= 60_000) { windowStart = now(); count = 0; }
    if (count >= maxRequests || active >= maxConcurrent)
      return json({ detail: "gateway busy; retry later" }, 429, { "Retry-After": "60" });
    count++; active++;
    try {
      const upstream = await fetcher(new URL(url.pathname + url.search, origin), {
        method: "GET", headers: { Accept: "application/json" },
        redirect: "manual", signal: AbortSignal.timeout(15_000),
      });
      if (!upstream.ok) {
        await upstream.body?.cancel();
        const status = [404, 429, 502, 503, 504].includes(upstream.status) ? upstream.status : 502;
        return json({ detail: "music service unavailable" }, status,
          status === 429 ? { "Retry-After": "60" } : {});
      }
      // Bound response size before parsing; never relay raw HTML or error content.
      const reader = upstream.body?.getReader();
      if (!reader) return json({ detail: "invalid music response" }, 502);
      const chunks: Uint8Array[] = []; let size = 0;
      try {
        while (true) {
          const part = await reader.read();
          if (part.done) break;
          size += part.value.length;
          if (size > 2_000_000) { await reader.cancel(); return json({ detail: "music response too large" }, 502); }
          chunks.push(part.value);
        }
      } finally { reader.releaseLock(); }
      const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (!payload || typeof payload !== "object" || Array.isArray(payload))
        return json({ detail: "invalid music response" }, 502);
      return json(payload);
    } catch {
      return json({ detail: "music service unavailable" }, 502);
    } finally { active--; }
  };
}

// Node can import this file for offline tests; Railway runs it with Bun.
if (typeof Bun !== "undefined" && import.meta.main) {
  Bun.serve({ hostname: "::", port: Number(Bun.env.PORT ?? "8080"), fetch: makeGateway(Bun.env) });
}
