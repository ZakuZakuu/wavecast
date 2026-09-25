export function resolveAuthDatabaseUrl(
  betterAuthDatabaseUrl = process.env.BETTER_AUTH_DATABASE_URL,
  wavecastDatabaseUrl = process.env.WAVECAST_DATABASE_URL,
): string | undefined {
  if (betterAuthDatabaseUrl) return betterAuthDatabaseUrl;
  if (!wavecastDatabaseUrl) return undefined;
  return wavecastDatabaseUrl.replace(
    /^postgresql\+asyncpg:\/\//,
    "postgresql://",
  );
}
