"use client";

import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MatterFilters } from "@/lib/api";

interface FilterBarProps {
  search: string;
  onSearchChange: (value: string) => void;
  status: string;
  onStatusChange: (value: string) => void;
  practiceArea: string;
  onPracticeAreaChange: (value: string) => void;
  clientName: string;
  onClientNameChange: (value: string) => void;
  filters?: MatterFilters;
  onClearFilters: () => void;
}

export function FilterBar({
  search,
  onSearchChange,
  status,
  onStatusChange,
  practiceArea,
  onPracticeAreaChange,
  clientName,
  onClientNameChange,
  filters,
  onClearFilters,
}: FilterBarProps) {
  const hasActiveFilters = search || status || practiceArea || clientName;

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative flex-1 min-w-[200px] max-w-[300px]">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search matters..."
          className="pl-8"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>

      <Select value={status} onValueChange={onStatusChange}>
        <SelectTrigger className="w-[140px]">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Statuses</SelectItem>
          {filters?.statuses.map((s) => (
            <SelectItem key={s} value={s}>
              {s}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={practiceArea} onValueChange={onPracticeAreaChange}>
        <SelectTrigger className="w-[160px]">
          <SelectValue placeholder="Practice Area" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Practice Areas</SelectItem>
          {filters?.practice_areas.map((p) => (
            <SelectItem key={p} value={p}>
              {p}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={clientName} onValueChange={onClientNameChange}>
        <SelectTrigger className="w-[180px]">
          <SelectValue placeholder="Client" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Clients</SelectItem>
          {filters?.clients.map((c) => (
            <SelectItem key={c} value={c}>
              {c}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {hasActiveFilters && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onClearFilters}
          className="h-9"
        >
          <X className="h-4 w-4 mr-1" />
          Clear
        </Button>
      )}
    </div>
  );
}
