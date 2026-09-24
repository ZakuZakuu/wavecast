export type SynchronizationGuard = {
  start: () => number;
  invalidate: () => void;
  isCurrent: (generation: number, listenerActive: boolean) => boolean;
};

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
