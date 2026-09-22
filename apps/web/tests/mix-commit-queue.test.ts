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
});
