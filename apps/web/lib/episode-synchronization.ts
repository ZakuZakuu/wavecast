export type SynchronizationGuard = {
  start: () => number;
  invalidate: () => void;
  isCurrent: (generation: number, listenerActive: boolean) => boolean;
};
export type EffectGenerationGuard = {
  start: () => number;
  isCurrent: (generation: number) => boolean;
};

export function createEffectGenerationGuard(): EffectGenerationGuard {
  let currentGeneration = 0;

  return {
    start: () => {
      currentGeneration += 1;
      return currentGeneration;
    },
    isCurrent: (generation) => generation === currentGeneration,
  };
}


export function createSynchronizationGuard(): SynchronizationGuard {
  let currentGeneration = 0;

  return {
    start: () => {
      currentGeneration += 1;
      return currentGeneration;
    },
    invalidate: () => {
      currentGeneration += 1;
    },
    isCurrent: (generation, listenerActive) =>
      listenerActive && generation === currentGeneration,
  };
}


export type IndependentSynchronizationTasks = {
  heartbeat: () => Promise<void>;
  buffer: () => Promise<void>;
};

export function createIndependentSynchronizationTasks(
  heartbeatTask: () => Promise<void>,
  bufferTask: () => Promise<void>,
): IndependentSynchronizationTasks {
  let heartbeating = false;
  let buffering = false;

  return {
    heartbeat: async () => {
      if (heartbeating) return;
      heartbeating = true;
      try {
        await heartbeatTask();
      } finally {
        heartbeating = false;
      }
    },
    buffer: async () => {
      if (buffering) return;
      buffering = true;
      try {
        await bufferTask();
      } finally {
        buffering = false;
      }
    },
  };
}
