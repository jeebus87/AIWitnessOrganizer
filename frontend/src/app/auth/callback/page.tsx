"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { useSyncStore } from "@/store/sync";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";

// Helper to wait for sync completion by polling sync-status endpoint
async function waitForSyncComplete(token: string, maxWaitMs: number = 60000): Promise<void> {
  const pollInterval = 2000; // Check every 2 seconds
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    try {
      const status = await api.getSyncStatus(token);
      if (!status.is_syncing) {
        return; // Sync complete
      }
    } catch (error) {
      console.error("Error checking sync status:", error);
      // Continue polling even on error
    }
    await new Promise(resolve => setTimeout(resolve, pollInterval));
  }

  // Timeout reached, proceed anyway
  console.warn("Sync status polling timed out");
}

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setToken, fetchUserProfile, setLoading } = useAuthStore();
  const { startSync, endSync, setSyncProgress } = useSyncStore();

  useEffect(() => {
    const token = searchParams.get("token");
    const error = searchParams.get("error");

    if (error) {
      router.push(`/login?error=${encodeURIComponent(error)}`);
      return;
    }

    if (token) {
      setLoading(true);
      setToken(token);

      // Fetch user profile then trigger full sync
      fetchUserProfile()
        .then(async () => {
          // Clear loading state FIRST so layout renders normally
          setLoading(false);

          // Start sync overlay
          startSync("Syncing matters from Clio");

          // Navigate to matters page where overlay will show
          router.push("/matters");

          try {
            // First sync matters (quick HTTP call)
            await api.syncMatters(token);

            // Check if any documents are still syncing in the background
            const status = await api.getSyncStatus(token);
            if (status.is_syncing) {
              // Wait for background document sync to complete
              await waitForSyncComplete(token, 60000);
            }
          } catch (syncError) {
            console.error("Sync error:", syncError);
          } finally {
            endSync();
          }
        })
        .catch(() => {
          setLoading(false);
          router.push("/login?error=Failed to fetch user profile");
        });
    } else {
      router.push("/login?error=No token received");
    }
  }, [searchParams, setToken, fetchUserProfile, setLoading, router, startSync, endSync, setSyncProgress]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-muted-foreground">Completing login...</p>
      </div>
    </div>
  );
}
