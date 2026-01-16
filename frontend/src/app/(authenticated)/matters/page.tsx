"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import useSWR from "swr";
import {
  RefreshCw,
  Play,
  Loader2,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Pagination } from "@/components/ui/pagination";
import { FilterBar } from "@/components/matters/filter-bar";
import { useAuthStore } from "@/store/auth";
import { api, MatterListResponse, MatterFilters } from "@/lib/api";
import { toast } from "sonner";

type SortField = "display_number" | "client_name" | "status" | "practice_area" | "last_synced_at" | "description";
type SortOrder = "asc" | "desc";

export default function MattersPage() {
  const { token } = useAuthStore();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Parse URL params
  const page = Number(searchParams.get("page")) || 1;
  const pageSize = Number(searchParams.get("pageSize")) || 20;
  const sortBy = (searchParams.get("sortBy") as SortField) || "display_number";
  const sortOrder = (searchParams.get("sortOrder") as SortOrder) || "asc";
  const search = searchParams.get("search") || "";
  const status = searchParams.get("status") || "";
  const practiceArea = searchParams.get("practiceArea") || "";
  const clientName = searchParams.get("clientName") || "";

  const [processingMatterId, setProcessingMatterId] = useState<number | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [searchInput, setSearchInput] = useState(search);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== search) {
        updateParams({ search: searchInput || null, page: "1" });
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Update URL params
  const updateParams = useCallback(
    (updates: Record<string, string | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([key, value]) => {
        if (value === null || value === "") {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      });
      router.push(`${pathname}?${params.toString()}`);
    },
    [searchParams, router, pathname]
  );

  // Fetch matters with current filters
  const {
    data: mattersResponse,
    isLoading,
    mutate,
  } = useSWR<MatterListResponse>(
    token
      ? ["matters", token, page, pageSize, sortBy, sortOrder, search, status, practiceArea, clientName]
      : null,
    () =>
      api.getMatters(token!, {
        page,
        pageSize,
        sortBy,
        sortOrder,
        search: search || undefined,
        status: status && status !== "all" ? status : undefined,
        practiceArea: practiceArea && practiceArea !== "all" ? practiceArea : undefined,
        clientName: clientName && clientName !== "all" ? clientName : undefined,
      })
  );

  // Fetch filter options
  const { data: filters } = useSWR<MatterFilters>(
    token ? ["matter-filters", token] : null,
    () => api.getMatterFilters(token!)
  );

  const matters = mattersResponse?.matters;
  const totalPages = mattersResponse?.total_pages || 0;

  const handleSync = async () => {
    if (!token) return;
    setSyncing(true);
    try {
      const result = await api.syncMatters(token);
      toast.success(`Synced ${result.matters_synced} matters from Clio`);
      mutate();
    } catch (error: any) {
      console.error("Sync error:", error);
      const errorMessage =
        error.response?.data?.detail || error.message || "Unknown error";
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

  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      updateParams({ sortOrder: sortOrder === "asc" ? "desc" : "asc" });
    } else {
      updateParams({ sortBy: field, sortOrder: "asc" });
    }
  };

  const handleClearFilters = () => {
    setSearchInput("");
    router.push(pathname);
  };

  const SortableHeader = ({
    field,
    children,
  }: {
    field: SortField;
    children: React.ReactNode;
  }) => (
    <TableHead
      className="cursor-pointer select-none hover:bg-muted/50"
      onClick={() => handleSort(field)}
    >
      <div className="flex items-center gap-1">
        {children}
        {sortBy === field ? (
          sortOrder === "asc" ? (
            <ArrowUp className="h-4 w-4" />
          ) : (
            <ArrowDown className="h-4 w-4" />
          )
        ) : (
          <ArrowUpDown className="h-4 w-4 opacity-30" />
        )}
      </div>
    </TableHead>
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
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Your Matters</CardTitle>
                <CardDescription>
                  {mattersResponse?.total || 0} matters synced from Clio
                </CardDescription>
              </div>
            </div>
            <FilterBar
              search={searchInput}
              onSearchChange={setSearchInput}
              status={status}
              onStatusChange={(v) => updateParams({ status: v, page: "1" })}
              practiceArea={practiceArea}
              onPracticeAreaChange={(v) => updateParams({ practiceArea: v, page: "1" })}
              clientName={clientName}
              onClientNameChange={(v) => updateParams({ clientName: v, page: "1" })}
              filters={filters}
              onClearFilters={handleClearFilters}
            />
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : matters?.length === 0 ? (
            <div className="py-8 text-center text-muted-foreground">
              {search || status || practiceArea || clientName
                ? "No matters match your filters"
                : "No matters synced yet. Click 'Sync with Clio' to get started."}
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <SortableHeader field="display_number">Matter</SortableHeader>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {matters?.map((matter) => (
                    <TableRow key={matter.id}>
                      <TableCell className="font-medium">
                        {matter.display_number || `#${matter.id}`}
                      </TableCell>
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

              {/* Pagination Controls */}
              <div className="flex items-center justify-between mt-4 pt-4 border-t">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span>Show</span>
                  <Select
                    value={pageSize.toString()}
                    onValueChange={(v) =>
                      updateParams({ pageSize: v, page: "1" })
                    }
                  >
                    <SelectTrigger className="w-[70px] h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="10">10</SelectItem>
                      <SelectItem value="20">20</SelectItem>
                      <SelectItem value="50">50</SelectItem>
                      <SelectItem value="100">100</SelectItem>
                    </SelectContent>
                  </Select>
                  <span>per page</span>
                </div>

                <div className="flex items-center gap-4">
                  <span className="text-sm text-muted-foreground">
                    Page {page} of {totalPages}
                  </span>
                  <Pagination
                    page={page}
                    totalPages={totalPages}
                    onPageChange={(p) => updateParams({ page: p.toString() })}
                  />
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
