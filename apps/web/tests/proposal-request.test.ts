import { beforeEach, describe, expect, it } from "vitest";

import { proposalRequest } from "../lib/proposal-request";
import { STATIONS } from "../lib/stations";

beforeEach(() => window.localStorage.clear());

describe("what the tuner asks the server for", () => {
  const night = STATIONS.find((station) => station.id === "night")!;

  it("leaves the host out unless the listener chose it, so the station's default and the wording stay in charge", () => {
    const request = proposalRequest(night, "睡前听点安静的", "SHORT");
    expect(request).not.toHaveProperty("host_mode");
    expect(proposalRequest(night, "睡前听点安静的", "SHORT", null)).not.toHaveProperty("host_mode");
  });

  it("sends the host the listener chose", () => {
    expect(proposalRequest(night, "睡前听点安静的", "SHORT", "FULL")).toMatchObject({ host_mode: "FULL", station: "night" });
    expect(proposalRequest(night, "睡前听点安静的", "DEEP", "NONE")).toMatchObject({ host_mode: "NONE", duration_intent: "DEEP" });
  });

  it("falls back to the station's own topic for an empty box", () => {
    expect(proposalRequest(night, "  ", "SHORT").prompt).toBe(night.defaultTopic);
  });
});
