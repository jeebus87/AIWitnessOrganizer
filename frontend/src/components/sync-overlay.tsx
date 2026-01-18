"use client";

import { useSyncStore } from "@/store/sync";
import { cn } from "@/lib/utils";

export function SyncOverlay() {
  const { isSyncing, syncMessage } = useSyncStore();

  if (!isSyncing) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70">
      <div className="flex flex-col items-center gap-6 text-center px-4">
        {/* Animated spinner */}
        <div className="relative">
          <div className="h-16 w-16 rounded-full border-4 border-blue-500/30" />
          <div className="absolute inset-0 h-16 w-16 rounded-full border-4 border-transparent border-t-blue-500 animate-spin" />
        </div>

        {/* Gradient text message with animated ellipsis */}
        <div className="flex items-baseline gap-0">
          <span className="text-2xl font-semibold bg-gradient-to-r from-blue-400 via-blue-500 to-blue-600 bg-clip-text text-transparent">
            {syncMessage}
          </span>
          <AnimatedEllipsis />
        </div>

        {/* Subtext */}
        <p className="text-sm text-blue-300/70">
          Please wait while we sync your data
        </p>
      </div>
    </div>
  );
}

function AnimatedEllipsis() {
  return (
    <span className="inline-flex w-6 ml-0.5">
      <span className="animate-ellipsis-1 text-2xl font-semibold bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">.</span>
      <span className="animate-ellipsis-2 text-2xl font-semibold bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">.</span>
      <span className="animate-ellipsis-3 text-2xl font-semibold bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">.</span>
    </span>
  );
}
