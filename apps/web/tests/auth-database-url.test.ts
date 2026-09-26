import { describe, expect, it } from "vitest";

import { resolveAuthDatabaseUrl } from "../lib/auth-database-url";

describe("Better Auth database URL", () => {
  it("prefers a dedicated PostgreSQL URL", () => {
    expect(
      resolveAuthDatabaseUrl(
        "postgres://auth-host/wavecast",
        "postgresql+asyncpg://api-host/wavecast",
      ),
    ).toBe("postgres://auth-host/wavecast");
  });

  it("normalizes the WaveCast asyncpg URL for node-postgres", () => {
    expect(
      resolveAuthDatabaseUrl(undefined, "postgresql+asyncpg://api-host/wavecast"),
    ).toBe("postgresql://api-host/wavecast");
  });

  it("preserves standard WaveCast PostgreSQL URLs and handles missing configuration", () => {
    expect(resolveAuthDatabaseUrl(undefined, "postgres://api-host/wavecast"))
      .toBe("postgres://api-host/wavecast");
    expect(resolveAuthDatabaseUrl(undefined, undefined)).toBeUndefined();
  });
});
