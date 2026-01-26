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

/**
 * Parse simple markdown formatting to HTML.
 * Supports: **bold**, *italic*, and line breaks for sections.
 */
function parseMarkdown(text: string): string {
  if (!text) return "";

  return text
    // Convert **text** to bold
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-foreground">$1</strong>')
    // Convert *text* to italic (but not inside bold)
    .replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>')
    // Convert line breaks to <br> for readability
    .replace(/\n/g, '<br />')
    // Replace em dashes and en dashes with comma
    .replace(/—/g, ', ')
    .replace(/–/g, ', ');
}

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

  // Generate/fetch results when dialog opens
  useEffect(() => {
    if (open && jobId && token) {
      setLoading(true);
      // Use generate endpoint - returns existing results or creates new ones
      api.generateLegalResearch(jobId, token)
        .then((data) => {
          setResearchData(data);
          // Pre-select top 5 results
          if (data.results && data.results.length > 0) {
            const topIds = data.results.slice(0, 5).map(r => r.id);
            setSelectedIds(new Set(topIds));
          }
        })
        .catch((err) => {
          console.error("Failed to generate legal research:", err);
          // Show specific error message based on error type
          const errorMsg = err?.response?.data?.detail || err?.message || "";
          if (errorMsg.includes("rate limit") || errorMsg.includes("429")) {
            toast.error("AI service busy. Please wait a minute and try again.");
          } else if (errorMsg.includes("unavailable") || errorMsg.includes("503")) {
            toast.error("Service temporarily unavailable. Please try again in a few minutes.");
          } else if (errorMsg.includes("timeout") || errorMsg.includes("504")) {
            toast.error("Request timed out. Please try again.");
          } else {
            toast.error("Failed to generate legal research. Please try again.");
          }
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
    // If no research data (API failed or no results), just close the dialog
    if (!researchData?.id) {
      onOpenChange(false);
      return;
    }

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
      <DialogContent position="top" className="max-w-6xl max-h-[85vh] flex flex-col">
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
            <div className="flex flex-col items-center justify-center h-full py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground mt-3">Analyzing case law and generating IRAC breakdowns...</p>
            </div>
          ) : !hasResults ? (
            <div className="flex flex-col items-center justify-center h-full py-12 text-muted-foreground">
              <BookOpen className="h-12 w-12 mb-4" />
              <p>No relevant case law found for this job.</p>
            </div>
          ) : (
            <div className="space-y-4 py-2">
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
  const hasIrac = result.irac_issue || result.irac_rule || result.irac_application || result.irac_conclusion;

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
      {/* Header row with checkbox and case name */}
      <div className="flex items-start gap-3 mb-3">
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

        {/* Case name and citation */}
        <div className="flex-1 min-w-0">
          <h4 className="font-medium text-sm leading-tight">{result.case_name}</h4>
          <p className="text-xs text-muted-foreground mt-1">
            {result.citation && <span className="font-mono">{result.citation}</span>}
            {result.citation && result.court && " | "}
            {result.court}
            {(result.citation || result.court) && result.date_filed && " | "}
            {result.date_filed}
          </p>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 ml-8">
        {/* Left column: Why Relevant, Snippet, Link */}
        <div className="space-y-3">
          {result.relevance_explanation && (
            <div className="text-xs">
              <span className="font-medium text-primary">Why Relevant: </span>
              <span className="text-muted-foreground">{result.relevance_explanation}</span>
            </div>
          )}

          {result.snippet && (
            <div className="p-2 bg-muted/50 rounded text-xs">
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
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            View on CourtListener
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>

        {/* Right column: IRAC Analysis */}
        {hasIrac && (
          <div className="space-y-2 border-l pl-4 lg:border-l-0 lg:pl-0 lg:border-t-0 border-t pt-3 lg:pt-0">
            <h5 className="font-semibold text-xs text-muted-foreground uppercase tracking-wide mb-2">
              IRAC Analysis
            </h5>

            {result.irac_issue && (
              <div className="border-l-4 border-red-500 pl-2">
                <h6 className="font-semibold text-xs text-red-600 dark:text-red-400 uppercase">Issue</h6>
                <p className="text-xs text-muted-foreground mt-0.5">{result.irac_issue}</p>
              </div>
            )}

            {result.irac_rule && (
              <div className="border-l-4 border-blue-500 pl-2">
                <h6 className="font-semibold text-xs text-blue-600 dark:text-blue-400 uppercase">Rule</h6>
                <p className="text-xs text-muted-foreground mt-0.5">{result.irac_rule}</p>
              </div>
            )}

            {result.irac_application && (
              <div className="border-l-4 border-amber-500 pl-2">
                <h6 className="font-semibold text-xs text-amber-600 dark:text-amber-400 uppercase">Application</h6>
                <p className="text-xs text-muted-foreground mt-0.5">{result.irac_application}</p>
              </div>
            )}

            {result.irac_conclusion && (
              <div className="border-l-4 border-green-500 pl-2">
                <h6 className="font-semibold text-xs text-green-600 dark:text-green-400 uppercase">Conclusion</h6>
                <p className="text-xs text-muted-foreground mt-0.5">{result.irac_conclusion}</p>
              </div>
            )}

            {result.case_utility && (
              <div className="border-l-4 border-purple-500 pl-2 mt-3 pt-2 border-t border-border">
                <h6 className="font-semibold text-xs text-purple-600 dark:text-purple-400 uppercase">How This Helps Your Case</h6>
                <div
                  className="text-xs text-foreground mt-0.5 space-y-1"
                  dangerouslySetInnerHTML={{ __html: parseMarkdown(result.case_utility) }}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
