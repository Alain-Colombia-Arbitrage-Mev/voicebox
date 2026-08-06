import { create } from 'zustand';

/** Deferred story placement for a generation that is still rendering. */
export interface PendingStoryAdd {
  storyId: string;
  /** Explicit timeline position; omit to append after the last clip. */
  startTimeMs?: number;
  /** Explicit track; omit for the main narration track. */
  track?: number;
}

interface GenerationState {
  /** IDs of generations currently in progress */
  pendingGenerationIds: Set<string>;
  /** Whether any generation is in progress (derived from pendingGenerationIds) */
  isGenerating: boolean;
  /** Map of generationId → deferred story placement */
  pendingStoryAdds: Map<string, PendingStoryAdd>;
  addPendingGeneration: (id: string) => void;
  removePendingGeneration: (id: string) => void;
  addPendingStoryAdd: (
    generationId: string,
    storyId: string,
    placement?: Omit<PendingStoryAdd, 'storyId'>,
  ) => void;
  removePendingStoryAdd: (generationId: string) => PendingStoryAdd | undefined;
  setActiveGenerationId: (id: string | null) => void;
  activeGenerationId: string | null;
}

export const useGenerationStore = create<GenerationState>((set, get) => ({
  pendingGenerationIds: new Set(),
  isGenerating: false,
  activeGenerationId: null,
  pendingStoryAdds: new Map(),

  addPendingGeneration: (id) =>
    set((state) => {
      const next = new Set(state.pendingGenerationIds);
      next.add(id);
      return { pendingGenerationIds: next, isGenerating: true };
    }),

  removePendingGeneration: (id) =>
    set((state) => {
      const next = new Set(state.pendingGenerationIds);
      next.delete(id);
      return { pendingGenerationIds: next, isGenerating: next.size > 0 };
    }),

  addPendingStoryAdd: (generationId, storyId, placement) =>
    set((state) => {
      const next = new Map(state.pendingStoryAdds);
      next.set(generationId, { storyId, ...placement });
      return { pendingStoryAdds: next };
    }),

  removePendingStoryAdd: (generationId) => {
    const pending = get().pendingStoryAdds.get(generationId);
    if (pending) {
      set((state) => {
        const next = new Map(state.pendingStoryAdds);
        next.delete(generationId);
        return { pendingStoryAdds: next };
      });
    }
    return pending;
  },

  setActiveGenerationId: (id) => set({ activeGenerationId: id }),
}));
