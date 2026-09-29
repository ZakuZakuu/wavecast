import { createAuthClient } from "better-auth/react";
import { jwtClient } from "better-auth/client/plugins";

export const authClient = createAuthClient({ plugins: [jwtClient()] });

let cachedToken: string | undefined;
let tokenExpiresAt = 0;
let authUnavailableUntil = 0;
let tokenRequest: Promise<string | undefined> | undefined;

export async function getApiAuthToken(): Promise<string | undefined> {
  const now = Date.now();
  if (cachedToken && tokenExpiresAt > now + 60_000) return cachedToken;
  if (!cachedToken && authUnavailableUntil > now) return undefined;
  if (tokenRequest) return tokenRequest;

  tokenRequest = (async () => {
    let result: Awaited<ReturnType<typeof authClient.token>>;
    try {
      result = await authClient.token();
    } catch {
      cachedToken = undefined;
      tokenExpiresAt = 0;
      authUnavailableUntil = Date.now() + 30_000;
      return undefined;
    }

    const { data, error } = result;
    if (error) {
      cachedToken = undefined;
      tokenExpiresAt = 0;
      authUnavailableUntil = Date.now() + 30_000;
      return undefined;
    }
    if (!data?.token) {
      authUnavailableUntil = Date.now() + 30_000;
      return undefined;
    }

    cachedToken = data.token;
    authUnavailableUntil = 0;
    const payload = data.token.split(".")[1];
    try {
      const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))) as {
        exp?: number;
      };
      tokenExpiresAt = typeof decoded.exp === "number" ? decoded.exp * 1000 : Date.now();
    } catch {
      tokenExpiresAt = Date.now();
    }
    return cachedToken;
  })();

  try {
    return await tokenRequest;
  } finally {
    tokenRequest = undefined;
  }
}

function userIdFromToken(token: string): string | undefined {
  const payload = token.split(".")[1];
  if (!payload) return undefined;
  try {
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = JSON.parse(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="))) as {
      sub?: unknown;
    };
    return typeof decoded.sub === "string" && decoded.sub ? decoded.sub : undefined;
  } catch {
    return undefined;
  }
}

export async function getApiAuthUserId(): Promise<string | undefined> {
  const token = await getApiAuthToken();
  return token ? userIdFromToken(token) : undefined;
}

export async function getApiAuthTokenForUser(expectedUserId: string): Promise<string> {
  const token = await getApiAuthToken();
  if (!token || userIdFromToken(token) !== expectedUserId) {
    throw new Error("Could not verify the signed-in library identity");
  }
  return token;
}

export function clearApiAuthToken(): void {
  cachedToken = undefined;
  tokenExpiresAt = 0;
  authUnavailableUntil = 0;
}
