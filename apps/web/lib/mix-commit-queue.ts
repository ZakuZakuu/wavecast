export type LatestSegmentCommitQueue = {
  request: (segmentId: string) => void;
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

  const drain = () => {
    if (inFlightSegmentId || !desiredSegmentId) return;
    const segmentId = desiredSegmentId;
    if (options.isCurrent(segmentId)) {
      desiredSegmentId = null;
      return;
    }

    inFlightSegmentId = segmentId;
    void options.commit(segmentId)
      .then((response) => {
        if (desiredSegmentId === segmentId) options.onResponse(response, segmentId);
      })
      .catch((reason: unknown) => {
        if (desiredSegmentId === segmentId) options.onError(reason, segmentId);
      })
      .finally(() => {
        if (inFlightSegmentId !== segmentId) return;
        inFlightSegmentId = null;
        if (desiredSegmentId === segmentId) desiredSegmentId = null;
        drain();
      });
  };

  return {
    request: (segmentId) => {
      desiredSegmentId = segmentId;
      drain();
    },
    reset: () => {
      desiredSegmentId = null;
      inFlightSegmentId = null;
    },
  };
}
