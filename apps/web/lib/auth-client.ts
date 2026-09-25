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
    const { data, error } = await authClient.token();
    if (error) {
      const status = (error as { status?: number }).status;
      if (status === 401 || status === 503) {
        cachedToken = undefined;
        tokenExpiresAt = 0;
        authUnavailableUntil = Date.now() + 30_000;
        return undefined;
      }
      throw new Error("Could not verify the signed-in session");
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

export function clearApiAuthToken(): void {
  cachedToken = undefined;
  tokenExpiresAt = 0;
  authUnavailableUntil = 0;
}
