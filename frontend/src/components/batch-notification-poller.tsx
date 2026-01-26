"use client";

import { useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { api, BatchJobResponse } from "@/lib/api";
import { useAuthStore } from "@/store/auth";

const POLL_INTERVAL = 15000; // 15 seconds

export function BatchNotificationPoller() {
  const { token } = useAuthStore();
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const checkBatchJobs = useCallback(async () => {
    if (!token) return;

    try {
      const response = await api.getPendingBatchJobs(token);

      for (const job of response.jobs) {
        // Only notify for completed jobs that haven't been notified yet
        if ((job.status === "Completed" || job.status === "Failed") && !job.user_notified) {
          if (job.status === "Completed") {
            if (job.job_type === "legal_research") {
              toast.success("Legal research analysis complete! Click 'Case Law' to view results.");
            } else if (job.job_type === "witness_extraction") {
              toast.success("Witness extraction complete! View your results.");
            }
          } else if (job.status === "Failed") {
            if (job.job_type === "legal_research") {
              toast.error(`Legal research analysis failed: ${job.error_message || "Unknown error"}`);
            } else if (job.job_type === "witness_extraction") {
              toast.error(`Witness extraction failed: ${job.error_message || "Unknown error"}`);
            }
          }

          // Mark as notified
          try {
            await api.markBatchJobNotified(job.id, token);
          } catch (err) {
            console.error("Failed to mark batch job as notified:", err);
          }
        }
      }
    } catch (err) {
      // Silently fail - don't spam the user with polling errors
      console.debug("Batch job poll error:", err);
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;

    // Initial check
    checkBatchJobs();

    // Set up polling
    pollRef.current = setInterval(checkBatchJobs, POLL_INTERVAL);

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
      }
    };
  }, [token, checkBatchJobs]);

  // This component doesn't render anything
  return null;
}
