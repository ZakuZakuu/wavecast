export type LatestSegmentCommitQueue = {
  request: (segmentId: string) => void;
  acknowledge: (segmentId: string | null) => void;
  runExclusive: <T>(operation: () => Promise<T>) => Promise<T>;
  reset: () => void;
};

export function createLatestSegmentCommitQueue<T>(options: {
  commit: (segmentId: string) => Promise<T>;
  isCurrent: (segmentId: string) => boolean;
  onResponse: (response: T, segmentId: string) => void;
  onError: (reason: unknown, segmentId: string) => void;
}): LatestSegmentCommitQueue {
  let desiredSegmentId: string | null = null;
  let inFlightSegmentId: string | null = null;
  let acknowledgedSegmentId: string | null = null;
  let exclusiveActive = false;
  let exclusivePendingCount = 0;
  let exclusiveTail: Promise<unknown> = Promise.resolve();
  let inFlightPromise: Promise<void> | null = null;

  const drain = () => {
    if (exclusiveActive || inFlightSegmentId || !desiredSegmentId) return;
    const segmentId = desiredSegmentId;
    if (options.isCurrent(segmentId) || acknowledgedSegmentId === segmentId) {
      desiredSegmentId = null;
      return;
    }

    inFlightSegmentId = segmentId;
    inFlightPromise = options.commit(segmentId)
      .then((response) => {
        if (desiredSegmentId === segmentId) options.onResponse(response, segmentId);
      })
      .catch((reason: unknown) => {
        if (desiredSegmentId === segmentId) options.onError(reason, segmentId);
      })
      .finally(() => {
        if (inFlightSegmentId !== segmentId) return;
        inFlightSegmentId = null;
        inFlightPromise = null;
        if (desiredSegmentId === segmentId) desiredSegmentId = null;
        drain();
      });
  };

  return {
    request: (segmentId) => {
      desiredSegmentId = segmentId;
      drain();
    },
    acknowledge: (segmentId) => {
      acknowledgedSegmentId = segmentId;
      desiredSegmentId = null;
    },
    runExclusive: <T>(operation: () => Promise<T>) => {
      exclusivePendingCount += 1;
      exclusiveActive = true;
      const run = exclusiveTail.then(async () => {
        const pendingCommit = inFlightPromise;
        if (pendingCommit) await pendingCommit;
        try {
          return await operation();
        } finally {
          exclusivePendingCount -= 1;
          if (exclusivePendingCount === 0) {
            exclusiveActive = false;
            drain();
          }
        }
      });
      exclusiveTail = run.then(() => undefined, () => undefined);
      return run;
    },
    reset: () => {
      desiredSegmentId = null;
      acknowledgedSegmentId = null;
      inFlightSegmentId = null;
      inFlightPromise = null;
      exclusiveActive = false;
    },
  };
}
