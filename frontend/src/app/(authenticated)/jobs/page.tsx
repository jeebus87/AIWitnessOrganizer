"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  Download,
  FileText,
  FileSpreadsheet,
  Ban,
  Trash2,
  Archive,
  ArchiveRestore,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthStore } from "@/store/auth";
import { api, ProcessingJob, JobStatus, JobListResponse, JobStats } from "@/lib/api";
import { toast } from "sonner";

const statusConfig: Record<JobStatus, { icon: typeof Clock; color: string; label: string }> = {
  pending: { icon: Clock, color: "text-yellow-500", label: "Pending" },
  processing: { icon: Loader2, color: "text-blue-500", label: "Processing" },
  completed: { icon: CheckCircle, color: "text-green-500", label: "Completed" },
  failed: { icon: XCircle, color: "text-red-500", label: "Failed" },
  cancelled: { icon: Ban, color: "text-gray-500", label: "Cancelled" },
};

function formatDate(dateString: string | null) {
  if (!dateString) return "—";
  return new Date(dateString).toLocaleString();
}

function getProgressPercent(job: ProcessingJob) {
  if (job.total_documents === 0) return 0;
  return Math.round((job.processed_documents / job.total_documents) * 100);
}

export default function JobsPage() {
  const { token } = useAuthStore();
  const [showArchived, setShowArchived] = useState(false);

  const {
    data: jobsResponse,
    isLoading,
    mutate,
  } = useSWR<JobListResponse>(
    token ? ["jobs", token, showArchived] : null,
    () => api.getJobs(token!, showArchived)
  );

  const {
    data: stats,
    mutate: mutateStats,
  } = useSWR<JobStats>(
    token ? ["job-stats", token] : null,
    () => api.getJobStats(token!)
  );

  const jobs = jobsResponse?.jobs;

  // Debug logging for job data
  useEffect(() => {
    if (jobs && jobs.length > 0) {
      console.log("[Jobs Page] Received jobs data:", jobs.map(j => ({
        id: j.id,
        job_number: j.job_number,
        status: j.status,
        processed: j.processed_documents,
        total: j.total_documents,
        matter_name: j.matter_name,
      })));
    }
  }, [jobs]);

  // Auto-refresh for active jobs
  useEffect(() => {
    const hasActiveJobs = jobs?.some(
      (job) => job.status === "pending" || job.status === "processing"
    );

    if (hasActiveJobs) {
      const interval = setInterval(() => {
        mutate();
        mutateStats();
      }, 5000);

      return () => clearInterval(interval);
    }
  }, [jobs, mutate, mutateStats]);

  const handleCancel = async (jobId: number) => {
    if (!token) return;
    try {
      await api.cancelJob(jobId, token);
      toast.success("Job cancelled");
      mutate();
      mutateStats();
    } catch (error) {
      toast.error("Failed to cancel job");
      console.error(error);
    }
  };

  const handleArchive = async (jobId: number) => {
    if (!token) return;
    try {
      await api.archiveJob(jobId, token);
      toast.success("Job archived");
      mutate();
      mutateStats();
    } catch (error) {
      toast.error("Failed to archive job");
      console.error(error);
    }
  };

  const handleUnarchive = async (jobId: number) => {
    if (!token) return;
    try {
      await api.unarchiveJob(jobId, token);
      toast.success("Job unarchived");
      mutate();
      mutateStats();
    } catch (error) {
      toast.error("Failed to unarchive job");
      console.error(error);
    }
  };

  const handleExport = async (jobId: number, format: "pdf" | "excel") => {
    if (!token) return;
    try {
      const url = format === "pdf"
        ? api.getExportPdfUrl(jobId)
        : api.getExportExcelUrl(jobId);

      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!response.ok) {
        throw new Error("Export failed");
      }

      const blob = await response.blob();
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = downloadUrl;
      a.download = `witnesses-job-${jobId}.${format === "pdf" ? "pdf" : "xlsx"}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(downloadUrl);
      document.body.removeChild(a);
      toast.success(`${format.toUpperCase()} downloaded`);
    } catch (error) {
      toast.error(`Failed to export ${format.toUpperCase()}`);
      console.error(error);
    }
  };


  const handleDelete = async (jobId: number) => {
    if (!token) return;
    try {
      await api.deleteJob(jobId, token);
      toast.success("Job deleted");
      mutate();
      mutateStats();
    } catch (error) {
      toast.error("Failed to delete job");
      console.error(error);
    }
  };

  const handleClearFinished = async () => {
    if (!token) return;
    try {
      const result = await api.clearFinishedJobs(token);
      toast.success(`Cleared ${result.deleted_count} job(s)`);
      mutate();
      mutateStats();
    } catch (error) {
      toast.error("Failed to clear jobs");
      console.error(error);
    }
  };

  const cancelledOrFailedJobs = jobs?.filter(
    (job) => job.status === "cancelled" || job.status === "failed"
  ).length || 0;

  const activeJobs = jobs?.filter(
    (job) => job.status === "pending" || job.status === "processing"
  ).length;

  // Calculate non-archived completed jobs for stat card
  const nonArchivedCompleted = (stats?.completed || 0) - (stats?.archived || 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Processing Jobs</h1>
          <p className="text-muted-foreground">
            Track the status of your document processing jobs
          </p>
        </div>
        <div className="flex items-center gap-4">
          {cancelledOrFailedJobs > 0 && !showArchived && (
            <Button variant="outline" size="sm" onClick={handleClearFinished}>
              <Trash2 className="mr-2 h-4 w-4" />
              Clear {cancelledOrFailedJobs} finished
            </Button>
          )}
          {activeJobs ? (
            <Badge variant="secondary" className="text-sm">
              <Loader2 className="mr-2 h-3 w-3 animate-spin" />
              {activeJobs} active job{activeJobs > 1 ? "s" : ""}
            </Badge>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-5">
        <Card
          className={`cursor-pointer transition-colors ${!showArchived ? 'ring-2 ring-primary' : 'hover:bg-muted/50'}`}
          onClick={() => setShowArchived(false)}
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Jobs</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{(stats?.total || 0) - (stats?.archived || 0)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Completed</CardTitle>
            <CheckCircle className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{nonArchivedCompleted}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Processing</CardTitle>
            <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.processing || 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Failed</CardTitle>
            <XCircle className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.failed || 0}</div>
          </CardContent>
        </Card>
        <Card
          className={`cursor-pointer transition-colors ${showArchived ? 'ring-2 ring-primary' : 'hover:bg-muted/50'}`}
          onClick={() => setShowArchived(true)}
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Archived</CardTitle>
            <Archive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.archived || 0}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {showArchived ? "Archived Jobs" : "Job History"}
          </CardTitle>
          <CardDescription>
            {showArchived
              ? "Archived jobs that have been hidden from the main list"
              : "All document processing jobs and their status"
            }
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : jobs?.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground">
              {showArchived
                ? "No archived jobs. Archive completed jobs to move them here."
                : "No processing jobs yet. Go to Matters and start processing."
              }
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Job ID</TableHead>
                  <TableHead>Matter</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Witnesses Found</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs?.map((job) => {
                  const StatusIcon = statusConfig[job.status].icon;
                  const progress = getProgressPercent(job);

                  return (
                    <TableRow key={job.id}>
                      <TableCell className="font-mono" title={`DB ID: ${job.id}, Job Number: ${job.job_number}`}>
                        #{job.job_number ?? job.id}
                      </TableCell>
                      <TableCell className="max-w-xs truncate" title={job.matter_name || undefined}>
                        {job.matter_name || <span className="text-muted-foreground italic">Full Database</span>}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={statusConfig[job.status].color}
                        >
                          <StatusIcon
                            className={`mr-1 h-3 w-3 ${
                              job.status === "processing" ? "animate-spin" : ""
                            }`}
                          />
                          {statusConfig[job.status].label}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {/* Show "Counting..." when job is pending/processing but total not yet set by worker */}
                        {(job.status === "pending" || job.status === "processing") && job.total_documents === 0 ? (
                          <div className="flex items-center gap-2">
                            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                            <span className="text-sm text-muted-foreground">
                              Counting documents...
                            </span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <div className="h-2 w-24 rounded-full bg-muted overflow-hidden">
                              <div
                                className="h-full bg-primary transition-all"
                                style={{ width: `${progress}%` }}
                              />
                            </div>
                            <span className="text-sm text-muted-foreground">
                              {job.processed_documents}/{job.total_documents}
                              {job.total_documents > 0 && ` (${progress}%)`}
                            </span>
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">
                          {job.total_witnesses_found}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(job.started_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        {job.status === "completed" && !job.is_archived ? (
                          <div className="flex items-center justify-end gap-2">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="sm">
                                  <Download className="mr-2 h-4 w-4" />
                                  Export
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => handleExport(job.id, "pdf")}>
                                  <FileText className="mr-2 h-4 w-4" />
                                  Download PDF
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleExport(job.id, "excel")}>
                                  <FileSpreadsheet className="mr-2 h-4 w-4" />
                                  Download Excel
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleArchive(job.id)}
                              title="Archive job"
                            >
                              <Archive className="h-4 w-4" />
                            </Button>
                          </div>
                        ) : job.status === "completed" && job.is_archived ? (
                          <div className="flex items-center justify-end gap-2">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="sm">
                                  <Download className="mr-2 h-4 w-4" />
                                  Export
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => handleExport(job.id, "pdf")}>
                                  <FileText className="mr-2 h-4 w-4" />
                                  Download PDF
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleExport(job.id, "excel")}>
                                  <FileSpreadsheet className="mr-2 h-4 w-4" />
                                  Download Excel
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleUnarchive(job.id)}
                              title="Unarchive job"
                            >
                              <ArchiveRestore className="h-4 w-4" />
                            </Button>
                          </div>
                        ) : job.status === "processing" || job.status === "pending" ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleCancel(job.id)}
                          >
                            <Ban className="mr-2 h-4 w-4" />
                            Cancel
                          </Button>
                        ) : job.status === "failed" || job.status === "cancelled" ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDelete(job.id)}
                            className="text-muted-foreground hover:text-destructive"
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            Delete
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
