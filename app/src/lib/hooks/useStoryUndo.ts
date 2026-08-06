import { create } from 'zustand';
import { apiClient } from '@/lib/api/client';
import type { StoryItemDetail } from '@/lib/api/types';

/**
 * Snapshot-based undo/redo for the story timeline.
 *
 * Every mutating action (move, trim, split, duplicate, delete, volume,
 * add) pushes a snapshot of the timeline taken BEFORE the change. Undo
 * reconciles the server state back to that snapshot — items that appeared
 * since are removed, items that disappeared are re-added, and items whose
 * position/trim/volume drifted are restored. Reconciliation handles
 * compound actions (split = trim change + new item) with one uniform
 * mechanism, at the cost of re-added items receiving fresh ids (stale
 * deeper entries then restore by generation rather than id).
 */

export interface TimelineItemSnapshot {
  id: string;
  generation_id: string;
  version_id?: string;
  start_time_ms: number;
  track: number;
  trim_start_ms: number;
  trim_end_ms: number;
  volume: number;
}

const MAX_STACK = 50;

export function snapshotItems(items: StoryItemDetail[]): TimelineItemSnapshot[] {
  return items.map((item) => ({
    id: item.id,
    generation_id: item.generation_id,
    version_id: item.version_id,
    start_time_ms: item.start_time_ms,
    track: item.track,
    trim_start_ms: item.trim_start_ms || 0,
    trim_end_ms: item.trim_end_ms || 0,
    volume: item.volume ?? 1.0,
  }));
}

async function restoreSnapshot(storyId: string, snapshot: TimelineItemSnapshot[]): Promise<void> {
  const current = await apiClient.getStory(storyId);
  const snapById = new Map(snapshot.map((s) => [s.id, s]));
  const currentById = new Map(current.items.map((i) => [i.id, i]));

  // Remove items that didn't exist at snapshot time (splits, duplicates, adds)
  for (const item of current.items) {
    if (!snapById.has(item.id)) {
      await apiClient.removeStoryItem(storyId, item.id);
    }
  }

  for (const snap of snapshot) {
    const existing = currentById.get(snap.id);
    if (existing) {
      if (existing.start_time_ms !== snap.start_time_ms || existing.track !== snap.track) {
        await apiClient.moveStoryItem(storyId, snap.id, {
          start_time_ms: snap.start_time_ms,
          track: snap.track,
        });
      }
      if (
        (existing.trim_start_ms || 0) !== snap.trim_start_ms ||
        (existing.trim_end_ms || 0) !== snap.trim_end_ms
      ) {
        await apiClient.trimStoryItem(storyId, snap.id, {
          trim_start_ms: snap.trim_start_ms,
          trim_end_ms: snap.trim_end_ms,
        });
      }
      if ((existing.volume ?? 1.0) !== snap.volume) {
        await apiClient.updateStoryItemVolume(storyId, snap.id, { volume: snap.volume });
      }
    } else {
      // Item was deleted since the snapshot — re-add from its generation
      const created = await apiClient.addStoryItem(storyId, {
        generation_id: snap.generation_id,
        start_time_ms: snap.start_time_ms,
        track: snap.track,
      });
      if (snap.trim_start_ms || snap.trim_end_ms) {
        await apiClient.trimStoryItem(storyId, created.id, {
          trim_start_ms: snap.trim_start_ms,
          trim_end_ms: snap.trim_end_ms,
        });
      }
      if (snap.volume !== 1.0) {
        await apiClient.updateStoryItemVolume(storyId, created.id, { volume: snap.volume });
      }
    }
  }
}

interface StoryUndoState {
  undoStacks: Map<string, TimelineItemSnapshot[][]>;
  redoStacks: Map<string, TimelineItemSnapshot[][]>;
  /** True while a restore is running — guards double-fire from key repeat. */
  isRestoring: boolean;
  /** Call BEFORE a mutating action with the pre-action items. */
  push: (storyId: string, items: StoryItemDetail[]) => void;
  undo: (storyId: string, currentItems: StoryItemDetail[]) => Promise<boolean>;
  redo: (storyId: string, currentItems: StoryItemDetail[]) => Promise<boolean>;
  canUndo: (storyId: string) => boolean;
  canRedo: (storyId: string) => boolean;
}

export const useStoryUndo = create<StoryUndoState>((set, get) => ({
  undoStacks: new Map(),
  redoStacks: new Map(),
  isRestoring: false,

  push: (storyId, items) =>
    set((state) => {
      const undoStacks = new Map(state.undoStacks);
      const stack = [...(undoStacks.get(storyId) ?? []), snapshotItems(items)].slice(-MAX_STACK);
      undoStacks.set(storyId, stack);
      // A new action invalidates the redo branch
      const redoStacks = new Map(state.redoStacks);
      redoStacks.set(storyId, []);
      return { undoStacks, redoStacks };
    }),

  undo: async (storyId, currentItems) => {
    const { undoStacks, redoStacks, isRestoring } = get();
    const stack = undoStacks.get(storyId) ?? [];
    if (isRestoring || stack.length === 0) return false;

    const snapshot = stack[stack.length - 1];
    set({ isRestoring: true });
    try {
      await restoreSnapshot(storyId, snapshot);
      const nextUndo = new Map(undoStacks);
      nextUndo.set(storyId, stack.slice(0, -1));
      const nextRedo = new Map(redoStacks);
      nextRedo.set(storyId, [
        ...(redoStacks.get(storyId) ?? []),
        snapshotItems(currentItems),
      ]);
      set({ undoStacks: nextUndo, redoStacks: nextRedo });
      return true;
    } finally {
      set({ isRestoring: false });
    }
  },

  redo: async (storyId, currentItems) => {
    const { undoStacks, redoStacks, isRestoring } = get();
    const stack = redoStacks.get(storyId) ?? [];
    if (isRestoring || stack.length === 0) return false;

    const snapshot = stack[stack.length - 1];
    set({ isRestoring: true });
    try {
      await restoreSnapshot(storyId, snapshot);
      const nextRedo = new Map(redoStacks);
      nextRedo.set(storyId, stack.slice(0, -1));
      const nextUndo = new Map(undoStacks);
      nextUndo.set(storyId, [
        ...(undoStacks.get(storyId) ?? []),
        snapshotItems(currentItems),
      ]);
      set({ undoStacks: nextUndo, redoStacks: nextRedo });
      return true;
    } finally {
      set({ isRestoring: false });
    }
  },

  canUndo: (storyId) => (get().undoStacks.get(storyId) ?? []).length > 0,
  canRedo: (storyId) => (get().redoStacks.get(storyId) ?? []).length > 0,
}));
