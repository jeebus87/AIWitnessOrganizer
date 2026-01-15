"use client";

import { useState } from "react";
import useSWR from "swr";
import { Search, Download, FileSpreadsheet, FileText, Filter } from "lucide-react";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthStore } from "@/store/auth";
import { api, WitnessFilters, WitnessRole, ImportanceLevel, WitnessListResponse } from "@/lib/api";

const roleColors: Record<WitnessRole, string> = {
  plaintiff: "bg-blue-500",
  defendant: "bg-red-500",
  eyewitness: "bg-green-500",
  expert: "bg-purple-500",
  attorney: "bg-indigo-500",
  physician: "bg-teal-500",
  police_officer: "bg-amber-500",
  family_member: "bg-pink-500",
  colleague: "bg-cyan-500",
  bystander: "bg-gray-500",
  mentioned: "bg-slate-500",
  other: "bg-zinc-500",
};

const importanceColors: Record<ImportanceLevel, string> = {
  high: "text-red-500 border-red-500",
  medium: "text-yellow-500 border-yellow-500",
  low: "text-green-500 border-green-500",
};

export default function WitnessesPage() {
  const { token } = useAuthStore();
  const [searchQuery, setSearchQuery] = useState("");
  const [filters, setFilters] = useState<WitnessFilters>({});

  const { data: witnessesResponse, isLoading } = useSWR<WitnessListResponse>(
    token ? ["witnesses", token, filters] : null,
    () => api.getWitnesses(token!, filters)
  );

  const witnesses = witnessesResponse?.witnesses;

  const filteredWitnesses = witnesses?.filter(
    (witness) =>
      witness.full_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      witness.observation?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      witness.email?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleRoleFilter = (role: WitnessRole | undefined) => {
    setFilters((prev) => ({ ...prev, role }));
  };

  const handleImportanceFilter = (importance: ImportanceLevel | undefined) => {
    setFilters((prev) => ({ ...prev, importance }));
  };

  const clearFilters = () => {
    setFilters({});
    setSearchQuery("");
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Witnesses</h1>
          <p className="text-muted-foreground">
            All extracted witnesses from processed documents
          </p>
        </div>
        <div className="flex gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline">
                <Download className="mr-2 h-4 w-4" />
                Export
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuLabel>Export Format</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem>
                <FileText className="mr-2 h-4 w-4" />
                Export as PDF
              </DropdownMenuItem>
              <DropdownMenuItem>
                <FileSpreadsheet className="mr-2 h-4 w-4" />
                Export as Excel
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Witness Directory</CardTitle>
              <CardDescription>
                {witnesses?.length || 0} witnesses found across all processed documents
              </CardDescription>
            </div>
            <div className="flex gap-2">
              <div className="relative w-64">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search witnesses..."
                  className="pl-8"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon">
                    <Filter className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuLabel>Filter by Role</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => handleRoleFilter(undefined)}>
                    All Roles
                  </DropdownMenuItem>
                  {Object.keys(roleColors).map((role) => (
                    <DropdownMenuItem
                      key={role}
                      onClick={() => handleRoleFilter(role as WitnessRole)}
                    >
                      <div
                        className={`mr-2 h-2 w-2 rounded-full ${roleColors[role as WitnessRole]}`}
                      />
                      {role.replace("_", " ")}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel>Filter by Importance</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => handleImportanceFilter(undefined)}>
                    All Levels
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleImportanceFilter("high")}>
                    High Importance
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleImportanceFilter("medium")}>
                    Medium Importance
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => handleImportanceFilter("low")}>
                    Low Importance
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={clearFilters}>
                    Clear All Filters
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : filteredWitnesses?.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground">
              {searchQuery || Object.keys(filters).length > 0
                ? "No witnesses match your filters"
                : "No witnesses extracted yet. Process some matters to get started."}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Importance</TableHead>
                  <TableHead>Observation</TableHead>
                  <TableHead>Contact</TableHead>
                  <TableHead>Confidence</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredWitnesses?.map((witness) => (
                  <TableRow key={witness.id}>
                    <TableCell className="font-medium">{witness.full_name}</TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="capitalize">
                        <div
                          className={`mr-1 h-2 w-2 rounded-full ${roleColors[witness.role]}`}
                        />
                        {witness.role.replace("_", " ")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={`capitalize ${importanceColors[witness.importance]}`}
                      >
                        {witness.importance}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-xs truncate">
                      {witness.observation || "—"}
                    </TableCell>
                    <TableCell>
                      <div className="text-sm">
                        {witness.email && (
                          <a href={`mailto:${witness.email}`} className="text-primary hover:underline">
                            {witness.email}
                          </a>
                        )}
                        {witness.phone && <div className="text-muted-foreground">{witness.phone}</div>}
                        {!witness.email && !witness.phone && "—"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-16 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full bg-primary"
                            style={{ width: `${(witness.confidence_score || 0) * 100}%` }}
                          />
                        </div>
                        <span className="text-sm text-muted-foreground">
                          {Math.round((witness.confidence_score || 0) * 100)}%
                        </span>
                      </div>
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
