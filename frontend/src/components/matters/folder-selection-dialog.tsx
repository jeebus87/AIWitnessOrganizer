"use client";
// Version: 2026-01-19-include-subfolders-fix

import { useState, useEffect } from "react";
import { ChevronRight, ChevronDown, Folder as FolderIcon, FolderOpen, Loader2, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { api, Folder } from "@/lib/api";
import { toast } from "sonner";

interface FolderSelectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  matterId: number;
  matterName: string;
  token: string;
  onConfirm: (options: {
    scanFolderId: number | null;
    legalAuthorityFolderId: number | null;
    includeSubfolders: boolean;
  }) => void;
}

interface FolderTreeItemProps {
  folder: Folder;
  level: number;
  selectedFolderId: number | null;
  legalAuthorityFolderId: number | null;
  onSelect: (folderId: number | null) => void;
  onSelectLegalAuthority: (folderId: number | null) => void;
  expandedFolders: Set<number>;
  toggleExpanded: (folderId: number) => void;
}

function FolderTreeItem({
  folder,
  level,
  selectedFolderId,
  legalAuthorityFolderId,
  onSelect,
  onSelectLegalAuthority,
  expandedFolders,
  toggleExpanded,
}: FolderTreeItemProps) {
  const hasChildren = folder.children && folder.children.length > 0;
  const isExpanded = expandedFolders.has(folder.id);
  const isSelected = selectedFolderId === folder.id;
  const isLegalAuthority = legalAuthorityFolderId === folder.id;

  return (
    <div className="select-none">
      <div
        className={cn(
          "flex items-center gap-1 py-1.5 px-2 rounded-md cursor-pointer hover:bg-muted/50",
          isSelected && "bg-primary/10 border border-primary/30",
          isLegalAuthority && "bg-amber-500/10 border border-amber-500/30"
        )}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={() => onSelect(folder.id)}
        onDoubleClick={() => {
          if (hasChildren) toggleExpanded(folder.id);
        }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              toggleExpanded(folder.id);
            }}
            className="p-0.5 hover:bg-muted rounded"
          >
            {isExpanded ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
        ) : (
          <div className="w-5" />
        )}

        {isExpanded ? (
          <FolderOpen className="h-4 w-4 text-amber-500" />
        ) : (
          <FolderIcon className="h-4 w-4 text-amber-500" />
        )}

        <span className="flex-1 text-sm truncate">{folder.name}</span>

        {isSelected && (
          <CheckCircle2 className="h-4 w-4 text-primary" />
        )}
        {isLegalAuthority && (
          <span className="text-xs bg-amber-500/20 text-amber-700 px-1.5 py-0.5 rounded">
            Legal Auth
          </span>
        )}
      </div>

      {isExpanded && hasChildren && (
        <div>
          {folder.children.map((child) => (
            <FolderTreeItem
              key={child.id}
              folder={child}
              level={level + 1}
              selectedFolderId={selectedFolderId}
              legalAuthorityFolderId={legalAuthorityFolderId}
              onSelect={onSelect}
              onSelectLegalAuthority={onSelectLegalAuthority}
              expandedFolders={expandedFolders}
              toggleExpanded={toggleExpanded}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function FolderSelectionDialog({
  open,
  onOpenChange,
  matterId,
  matterName,
  token,
  onConfirm,
}: FolderSelectionDialogProps) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [scanFolderId, setScanFolderId] = useState<number | null>(null);
  const [legalAuthorityFolderId, setLegalAuthorityFolderId] = useState<number | null>(null);
  const [includeSubfolders, setIncludeSubfolders] = useState(true);
  const [expandedFolders, setExpandedFolders] = useState<Set<number>>(new Set());

  const [selectionMode, setSelectionMode] = useState<"scan" | "legal">("scan");
  const [documentCount, setDocumentCount] = useState<number | null>(null);
  const [countLoading, setCountLoading] = useState(false);

  // Fetch folders when dialog opens
  useEffect(() => {
    if (open && matterId) {
      setLoading(true);
      setError(null);
      api.getMatterFolders(matterId, token)
        .then((response) => {
          setFolders(response.folders || []);
          // Auto-expand first level
          const firstLevelIds = new Set(response.folders?.map(f => f.id) || []);
          setExpandedFolders(firstLevelIds);
        })
        .catch((err) => {
          console.error("Failed to fetch folders:", err);
          setError(err.message || "Failed to load folders");
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [open, matterId, token]);

  // Reset state when dialog closes
  useEffect(() => {
    if (!open) {
      setScanFolderId(null);
      setLegalAuthorityFolderId(null);
      setIncludeSubfolders(true);
      setSelectionMode("scan");
      setDocumentCount(null);
    }
  }, [open]);

  // Fetch document count when scan folder or includeSubfolders changes
  const fetchDocumentCount = async (folderId: number | null, withSubfolders: boolean) => {
    if (!token || !matterId) return;

    setCountLoading(true);
    try {
      const folderIdStr = folderId ? folderId.toString() : null;
      console.log(`[DOC_COUNT] Requesting: matterId=${matterId}, folderId=${folderIdStr}, includeSubfolders=${withSubfolders}`);
      const result = await api.getDocumentCount(matterId, token, folderIdStr, withSubfolders);
      console.log(`[DOC_COUNT] Response:`, result);
      setDocumentCount(result.count);

      // Show toast with document count
      const folderName = folderId
        ? folders.flatMap(function findFolder(f): Folder[] {
            if (f.id === folderId) return [f];
            return f.children ? f.children.flatMap(findFolder) : [];
          })[0]?.name || "selected folder"
        : "all documents";

      toast.info(`${result.count.toLocaleString()} documents in ${folderName}`);
    } catch (err) {
      console.error("Failed to fetch document count:", err);
    } finally {
      setCountLoading(false);
    }
  };

  // Re-fetch count when includeSubfolders changes (for any selected folder including "all")
  useEffect(() => {
    if (open && documentCount !== null) {
      // Only re-fetch if we've already fetched a count (meaning user has selected something)
      fetchDocumentCount(scanFolderId, includeSubfolders);
    }
  }, [includeSubfolders]);

  const toggleExpanded = (folderId: number) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folderId)) {
        next.delete(folderId);
      } else {
        next.add(folderId);
      }
      return next;
    });
  };

  const handleFolderSelect = (folderId: number | null) => {
    if (selectionMode === "scan") {
      setScanFolderId(folderId);
      // Fetch and display document count when scan folder is selected
      fetchDocumentCount(folderId, includeSubfolders);
    } else {
      setLegalAuthorityFolderId(folderId);
    }
  };

  const handleConfirm = () => {
    onConfirm({
      scanFolderId,
      legalAuthorityFolderId,
      includeSubfolders,
    });
    onOpenChange(false);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl flex flex-col">
        <SheetHeader>
          <SheetTitle>Select Folders to Process</SheetTitle>
          <SheetDescription>
            Choose which folders to scan for {matterName}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-hidden flex flex-col gap-4 px-6">
          {/* Selection Mode Tabs */}
          <div className="flex gap-2">
            <Button
              variant={selectionMode === "scan" ? "default" : "outline"}
              size="sm"
              onClick={() => setSelectionMode("scan")}
            >
              Documents to Scan
              {scanFolderId && <CheckCircle2 className="ml-1.5 h-3.5 w-3.5" />}
            </Button>
            <Button
              variant={selectionMode === "legal" ? "default" : "outline"}
              size="sm"
              onClick={() => setSelectionMode("legal")}
            >
              Legal Authorities (Optional)
              {legalAuthorityFolderId && <CheckCircle2 className="ml-1.5 h-3.5 w-3.5" />}
            </Button>
          </div>

          {/* Selection Info */}
          <div className="text-sm text-muted-foreground">
            {selectionMode === "scan" ? (
              <p>
                Select a folder containing discovery documents to analyze.
                {!scanFolderId && " Leave empty to scan all documents in the matter."}
              </p>
            ) : (
              <p>
                Select a folder containing case law and legal standards.
                The AI will use these to determine witness relevance.
              </p>
            )}
          </div>

          {/* Folder Tree */}
          <div className="flex-1 border rounded-md overflow-auto min-h-[200px] max-h-[300px]">
            {loading ? (
              <div className="flex items-center justify-center h-full">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : error ? (
              <div className="flex items-center justify-center h-full text-destructive">
                {error}
              </div>
            ) : folders.length === 0 ? (
              <div className="flex items-center justify-center h-full text-muted-foreground">
                No folders found in this matter
              </div>
            ) : (
              <div className="p-2">
                {/* Root option */}
                <div
                  className={cn(
                    "flex items-center gap-2 py-1.5 px-2 rounded-md cursor-pointer hover:bg-muted/50",
                    selectionMode === "scan" && scanFolderId === null && "bg-primary/10 border border-primary/30"
                  )}
                  onClick={() => handleFolderSelect(null)}
                >
                  <FolderIcon className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm">
                    {selectionMode === "scan" ? "(All Documents in Matter)" : "(No Legal Authority Folder)"}
                  </span>
                  {selectionMode === "scan" && scanFolderId === null && (
                    <CheckCircle2 className="h-4 w-4 text-primary ml-auto" />
                  )}
                </div>

                {folders.map((folder) => (
                  <FolderTreeItem
                    key={folder.id}
                    folder={folder}
                    level={0}
                    selectedFolderId={selectionMode === "scan" ? scanFolderId : legalAuthorityFolderId}
                    legalAuthorityFolderId={legalAuthorityFolderId}
                    onSelect={handleFolderSelect}
                    onSelectLegalAuthority={setLegalAuthorityFolderId}
                    expandedFolders={expandedFolders}
                    toggleExpanded={toggleExpanded}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Options */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Switch
                id="include-subfolders"
                checked={includeSubfolders}
                onCheckedChange={setIncludeSubfolders}
              />
              <Label htmlFor="include-subfolders" className="text-sm">
                Include subfolders
              </Label>
            </div>

            {/* Selection Summary */}
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              <span>
                {scanFolderId ? "Scanning specific folder" : "Scanning all documents"}
                {legalAuthorityFolderId && " | Using legal authority folder"}
              </span>
              {countLoading && <Loader2 className="h-3 w-3 animate-spin" />}
              {documentCount !== null && !countLoading && (
                <span className="font-medium text-primary">
                  ({documentCount.toLocaleString()} documents)
                </span>
              )}
            </div>
          </div>
        </div>

        <SheetFooter className="gap-2 flex-row justify-end border-t pt-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleConfirm}>
            Start Processing
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
