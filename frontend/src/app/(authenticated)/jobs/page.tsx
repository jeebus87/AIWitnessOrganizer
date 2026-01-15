"use client";

import { useEffect } from "react";
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
import { api, ProcessingJob, JobStatus, JobListResponse } from "@/lib/api";
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

  const {
    data: jobsResponse,
    isLoading,
    mutate,
  } = useSWR<JobListResponse>(token ? ["jobs", token] : null, () =>
    api.getJobs(token!)
  );

  const jobs = jobsResponse?.jobs;

  // Auto-refresh for active jobs
  useEffect(() => {
    const hasActiveJobs = jobs?.some(
      (job) => job.status === "pending" || job.status === "processing"
    );

    if (hasActiveJobs) {
      const interval = setInterval(() => {
        mutate();
      }, 5000);

      return () => clearInterval(interval);
    }
  }, [jobs, mutate]);

  const handleCancel = async (jobId: number) => {
    if (!token) return;
    try {
      await api.cancelJob(jobId, token);
      toast.success("Job cancelled");
      mutate();
    } catch (error) {
      toast.error("Failed to cancel job");
      console.error(error);
    }
  };

  const activeJobs = jobs?.filter(
    (job) => job.status === "pending" || job.status === "processing"
  ).length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Processing Jobs</h1>
          <p className="text-muted-foreground">
            Track the status of your document processing jobs
          </p>
        </div>
        {activeJobs ? (
          <Badge variant="secondary" className="text-sm">
            <Loader2 className="mr-2 h-3 w-3 animate-spin" />
            {activeJobs} active job{activeJobs > 1 ? "s" : ""}
          </Badge>
        ) : null}
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Jobs</CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{jobs?.length || 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Completed</CardTitle>
            <CheckCircle className="h-4 w-4 text-green-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {jobs?.filter((j) => j.status === "completed").length || 0}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Processing</CardTitle>
            <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {jobs?.filter((j) => j.status === "processing").length || 0}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Failed</CardTitle>
            <XCircle className="h-4 w-4 text-red-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {jobs?.filter((j) => j.status === "failed").length || 0}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Job History</CardTitle>
          <CardDescription>
            All document processing jobs and their status
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
              No processing jobs yet. Go to Matters and start processing.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Job ID</TableHead>
                  <TableHead>Type</TableHead>
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
                      <TableCell className="font-mono">#{job.id}</TableCell>
                      <TableCell className="capitalize">
                        {job.job_type.replace("_", " ")}
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
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-24 rounded-full bg-muted overflow-hidden">
                            <div
                              className="h-full bg-primary transition-all"
                              style={{ width: `${progress}%` }}
                            />
                          </div>
                          <span className="text-sm text-muted-foreground">
                            {job.processed_documents}/{job.total_documents}
                          </span>
                        </div>
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
                        {job.status === "completed" ? (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="sm">
                                <Download className="mr-2 h-4 w-4" />
                                Export
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem asChild>
                                <a
                                  href={api.getExportPdfUrl(job.id)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  <FileText className="mr-2 h-4 w-4" />
                                  Download PDF
                                </a>
                              </DropdownMenuItem>
                              <DropdownMenuItem asChild>
                                <a
                                  href={api.getExportExcelUrl(job.id)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  <FileSpreadsheet className="mr-2 h-4 w-4" />
                                  Download Excel
                                </a>
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        ) : job.status === "processing" || job.status === "pending" ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleCancel(job.id)}
                          >
                            <Ban className="mr-2 h-4 w-4" />
                            Cancel
                          </Button>
                        ) : job.status === "failed" ? (
                          <span className="text-sm text-red-500">
                            {job.error_message || "Unknown error"}
                          </span>
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
