import { describe, expect, it, vi } from "vitest";

import { createLatestSegmentCommitQueue } from "../lib/mix-commit-queue";

describe("latest desired segment commit queue", () => {
  it("serializes commits and catches up to the latest segment", async () => {
    const resolvers: Array<(value: string) => void> = [];
    const commit = vi.fn((segmentId: string) => new Promise<string>((resolve) => {
      resolvers.push(() => resolve(segmentId));
    }));
    const responses: string[] = [];
    let current = "A";
    const queue = createLatestSegmentCommitQueue({
      commit,
      isCurrent: (segmentId) => current === segmentId,
      onResponse: (response, segmentId) => {
        current = segmentId;
        responses.push(response);
      },
      onError: vi.fn(),
    });

    queue.request("VOICE");
    queue.request("B");
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenLastCalledWith("VOICE");

    resolvers[0]("VOICE");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(commit).toHaveBeenCalledTimes(2);
    expect(commit).toHaveBeenLastCalledWith("B");

    resolvers[1]("B");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(responses).toEqual(["B"]);
    expect(current).toBe("B");
  });
  it("blocks explicit transport actions until automatic commits settle", async () => {
    const resolvers: Array<() => void> = [];
    const events: string[] = [];
    const commit = vi.fn((segmentId: string) => new Promise<string>((resolve) => {
      events.push("commit:start:" + segmentId);
      resolvers.push(() => {
        events.push("commit:end:" + segmentId);
        resolve(segmentId);
      });
    }));
    let current = "A";
    const queue = createLatestSegmentCommitQueue({
      commit,
      isCurrent: (segmentId) => current === segmentId,
      onResponse: (_response, segmentId) => { current = segmentId; },
      onError: vi.fn(),
    });

    queue.request("VOICE");
    const explicit = queue.runExclusive(async () => {
      events.push("seek:start");
      queue.acknowledge("B");
      events.push("seek:end");
    });
    queue.request("B");
    expect(events).toEqual(["commit:start:VOICE"]);

    resolvers[0]();
    await explicit;
    expect(events).toEqual(["commit:start:VOICE", "commit:end:VOICE", "seek:start", "seek:end"]);
    expect(commit).toHaveBeenCalledTimes(1);
    expect(current).toBe("A");
  });

});
