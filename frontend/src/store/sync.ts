import { create } from "zustand";

interface SyncState {
  isSyncing: boolean;
  syncMessage: string;
  syncProgress: number | null; // 0-100 or null for indeterminate
  setSyncing: (syncing: boolean, message?: string) => void;
  setSyncProgress: (progress: number | null) => void;
  startSync: (message?: string) => void;
  endSync: () => void;
}

export const useSyncStore = create<SyncState>()((set) => ({
  isSyncing: false,
  syncMessage: "Syncing with Clio",
  syncProgress: null,

  setSyncing: (syncing, message) =>
    set({
      isSyncing: syncing,
      syncMessage: message || "Syncing with Clio",
    }),

  setSyncProgress: (progress) => set({ syncProgress: progress }),

  startSync: (message = "Syncing with Clio") =>
    set({
      isSyncing: true,
      syncMessage: message,
      syncProgress: null,
    }),

  endSync: () =>
    set({
      isSyncing: false,
      syncMessage: "",
      syncProgress: null,
    }),
}));
