"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  RefreshCw,
  Play,
  Search,
  Loader2,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthStore } from "@/store/auth";
import { api, MatterListResponse } from "@/lib/api";
import { toast } from "sonner";

export default function MattersPage() {
  const { token } = useAuthStore();
  const [searchQuery, setSearchQuery] = useState("");
  const [processingMatterId, setProcessingMatterId] = useState<number | null>(null);
  const [syncing, setSyncing] = useState(false);

  const {
    data: mattersResponse,
    isLoading,
    mutate,
  } = useSWR<MatterListResponse>(token ? ["matters", token] : null, () =>
    api.getMatters(token!)
  );

  const matters = mattersResponse?.matters;

  const handleSync = async () => {
    if (!token) return;
    setSyncing(true);
    try {
      const result = await api.syncMatters(token);
      toast.success(`Synced ${result.synced} matters from Clio`);
      mutate();
    } catch (error: any) {
      console.error("Sync error:", error);
      // Try to extract detailed error message from API response
      const errorMessage = error.response?.data?.detail || error.message || "Unknown error";
      toast.error(`Sync failed: ${errorMessage}`);
    } finally {
      setSyncing(false);
    }
  };

  const handleProcess = async (matterId: number) => {
    if (!token) return;
    setProcessingMatterId(matterId);
    try {
      const job = await api.processMatter(matterId, token);
      toast.success(`Processing job started (ID: ${job.id})`);
    } catch (error) {
      toast.error("Failed to start processing");
      console.error(error);
    } finally {
      setProcessingMatterId(null);
    }
  };

  const filteredMatters = matters?.filter(
    (matter) =>
      matter.display_number?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      matter.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      matter.client_name?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Matters</h1>
          <p className="text-muted-foreground">
            Manage your legal matters synced from Clio
          </p>
        </div>
        <Button onClick={handleSync} disabled={syncing}>
          {syncing ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 h-4 w-4" />
          )}
          Sync with Clio
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Your Matters</CardTitle>
              <CardDescription>
                {matters?.length || 0} matters synced from Clio
              </CardDescription>
            </div>
            <div className="relative w-64">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search matters..."
                className="pl-8"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : filteredMatters?.length === 0 ? (
            <div className="py-8 text-center text-muted-foreground">
              {searchQuery
                ? "No matters match your search"
                : "No matters synced yet. Click 'Sync with Clio' to get started."}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Matter #</TableHead>
                  <TableHead>Client</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Practice Area</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredMatters?.map((matter) => (
                  <TableRow key={matter.id}>
                    <TableCell className="font-medium">
                      {matter.display_number || `#${matter.id}`}
                    </TableCell>
                    <TableCell>{matter.client_name || "—"}</TableCell>
                    <TableCell className="max-w-xs truncate">
                      {matter.description || "No description"}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          matter.status === "Open" ? "default" : "secondary"
                        }
                      >
                        {matter.status === "Open" ? (
                          <CheckCircle className="mr-1 h-3 w-3" />
                        ) : (
                          <XCircle className="mr-1 h-3 w-3" />
                        )}
                        {matter.status || "Unknown"}
                      </Badge>
                    </TableCell>
                    <TableCell>{matter.practice_area || "—"}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        onClick={() => handleProcess(matter.id)}
                        disabled={processingMatterId === matter.id}
                      >
                        {processingMatterId === matter.id ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Play className="mr-2 h-4 w-4" />
                        )}
                        Process
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
