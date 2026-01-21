"use client";

import { useState, useEffect } from "react";
import { Loader2, Check, ExternalLink, Scale, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { api, CaseLawResult, LegalResearchResponse } from "@/lib/api";
import { toast } from "sonner";

interface LegalResearchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  token: string;
  onComplete?: () => void;
}

export function LegalResearchDialog({
  open,
  onOpenChange,
  jobId,
  token,
  onComplete,
}: LegalResearchDialogProps) {
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [researchData, setResearchData] = useState<LegalResearchResponse | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  // Fetch results when dialog opens
  useEffect(() => {
    if (open && jobId && token) {
      setLoading(true);
      api.getLegalResearchForJob(jobId, token)
        .then((data) => {
          setResearchData(data);
          // Pre-select top 5 results
          if (data.results && data.results.length > 0) {
            const topIds = data.results.slice(0, 5).map(r => r.id);
            setSelectedIds(new Set(topIds));
          }
        })
        .catch((err) => {
          console.error("Failed to fetch legal research:", err);
          toast.error("Failed to load legal research results");
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [open, jobId, token]);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setResearchData(null);
      setSelectedIds(new Set());
    }
  }, [open]);

  const handleToggle = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleApprove = async () => {
    if (!researchData?.id) return;

    setSubmitting(true);
    try {
      await api.approveLegalResearch(researchData.id, token, Array.from(selectedIds));
      toast.success(`Saving ${selectedIds.size} case${selectedIds.size !== 1 ? 's' : ''} to Clio`);
      onOpenChange(false);
      onComplete?.();
    } catch (err) {
      console.error("Failed to approve legal research:", err);
      toast.error("Failed to save cases to Clio");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDismiss = async () => {
    if (!researchData?.id) return;

    setSubmitting(true);
    try {
      await api.dismissLegalResearch(researchData.id, token);
      toast.info("Legal research dismissed");
      onOpenChange(false);
      onComplete?.();
    } catch (err) {
      console.error("Failed to dismiss legal research:", err);
      toast.error("Failed to dismiss legal research");
    } finally {
      setSubmitting(false);
    }
  };

  const results = researchData?.results || [];
  const hasResults = researchData?.has_results && results.length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[50vh] flex flex-col relative">
        {/* Saving overlay */}
        {submitting && (
          <div className="absolute inset-0 bg-background/80 flex items-center justify-center z-50 rounded-lg">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="h-10 w-10 animate-spin text-primary" />
              <span className="text-sm font-medium">Saving cases to Clio...</span>
              <span className="text-xs text-muted-foreground">This may take a moment</span>
            </div>
          </div>
        )}

        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Scale className="h-5 w-5 text-primary" />
            Relevant Case Law Found
          </DialogTitle>
          <DialogDescription>
            We found potentially relevant case law based on your extracted witness observations.
            Select cases to save to your matter&apos;s Legal Research folder in Clio.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-auto min-h-[200px]">
          {loading ? (
            <div className="flex items-center justify-center h-full py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : !hasResults ? (
            <div className="flex flex-col items-center justify-center h-full py-12 text-muted-foreground">
              <BookOpen className="h-12 w-12 mb-4" />
              <p>No relevant case law found for this job.</p>
            </div>
          ) : (
            <div className="space-y-3 py-2">
              {results.map((result) => (
                <CaseLawCard
                  key={result.id}
                  result={result}
                  isSelected={selectedIds.has(result.id)}
                  onToggle={() => handleToggle(result.id)}
                />
              ))}
            </div>
          )}
        </div>

        <DialogFooter className="flex gap-2 border-t pt-4">
          {hasResults && (
            <div className="flex-1 text-sm text-muted-foreground">
              {selectedIds.size} of {results.length} selected
            </div>
          )}
          <Button
            variant="outline"
            onClick={handleDismiss}
            disabled={submitting || loading}
          >
            Dismiss
          </Button>
          {hasResults && (
            <Button
              onClick={handleApprove}
              disabled={selectedIds.size === 0 || submitting || loading}
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                <>Save {selectedIds.size} Case{selectedIds.size !== 1 ? 's' : ''} to Clio</>
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface CaseLawCardProps {
  result: CaseLawResult;
  isSelected: boolean;
  onToggle: () => void;
}

function CaseLawCard({ result, isSelected, onToggle }: CaseLawCardProps) {
  return (
    <div
      className={cn(
        "p-4 border rounded-lg cursor-pointer transition-all",
        isSelected
          ? "border-primary bg-primary/5 shadow-sm"
          : "border-border hover:bg-muted/50"
      )}
      onClick={onToggle}
    >
      <div className="flex items-start gap-3">
        {/* Checkbox */}
        <div
          className={cn(
            "mt-0.5 h-5 w-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors",
            isSelected
              ? "bg-primary border-primary text-primary-foreground"
              : "border-muted-foreground"
          )}
        >
          {isSelected && <Check className="h-3 w-3" />}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <h4 className="font-medium text-sm leading-tight">{result.case_name}</h4>
          <p className="text-xs text-muted-foreground mt-1">
            {result.citation && <span className="font-mono">{result.citation}</span>}
            {result.citation && result.court && " | "}
            {result.court}
            {(result.citation || result.court) && result.date_filed && " | "}
            {result.date_filed}
          </p>
          {result.matched_query && (
            <div className="mt-2 text-xs">
              <span className="font-medium text-primary">Matched: </span>
              <span className="text-muted-foreground italic">&quot;{result.matched_query}&quot;</span>
            </div>
          )}
          {result.snippet && (
            <div className="mt-2 p-2 bg-muted/50 rounded text-xs">
              <span className="font-medium text-foreground">Relevant excerpt: </span>
              <span
                className="text-muted-foreground"
                dangerouslySetInnerHTML={{
                  __html: result.snippet
                    .replace(/<mark>/g, '<mark class="bg-yellow-200 dark:bg-yellow-800 px-0.5 rounded">')
                }}
              />
            </div>
          )}
          <a
            href={result.absolute_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline mt-2"
            onClick={(e) => e.stopPropagation()}
          >
            View on CourtListener
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </div>
    </div>
  );
}
