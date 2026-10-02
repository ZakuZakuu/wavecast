import { describe, expect, it } from "vitest";

import { playerTargetFromPath } from "../lib/player-nav";

describe("playerTargetFromPath", () => {
  it("parses player routes and ignores everything else", () => {
    expect(playerTargetFromPath("/episode/materialized/e%201")).toEqual({ episodeId: "e 1" });
    expect(playerTargetFromPath("/episode/seed-1")).toEqual({ seedId: "seed-1" });
    expect(playerTargetFromPath("/episode/materialized")).toBeNull();
    expect(playerTargetFromPath("/tune")).toBeNull();
    expect(playerTargetFromPath(null)).toBeNull();
  });
});
