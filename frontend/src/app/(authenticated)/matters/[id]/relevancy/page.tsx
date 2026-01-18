"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle,
  Loader2,
  Plus,
  Shield,
  Trash2,
  Users,
  X,
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuthStore } from "@/store/auth";
import {
  api,
  RelevancyAnalysis,
  CaseClaimWithWitnesses,
  ClaimType,
  CreateClaimRequest,
} from "@/lib/api";
import { toast } from "sonner";

export default function RelevancyPage() {
  const params = useParams();
  const router = useRouter();
  const matterId = Number(params.id);
  const { token } = useAuthStore();

  const [addClaimDialogOpen, setAddClaimDialogOpen] = useState(false);
  const [newClaimType, setNewClaimType] = useState<ClaimType>("allegation");
  const [newClaimText, setNewClaimText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch relevancy data
  const {
    data: relevancy,
    isLoading,
    mutate,
    error,
  } = useSWR<RelevancyAnalysis>(
    token && matterId ? ["relevancy", matterId, token] : null,
    () => api.getRelevancy(matterId, token!)
  );

  const handleAddClaim = async () => {
    if (!token || !newClaimText.trim()) return;

    setIsSubmitting(true);
    try {
      const claim: CreateClaimRequest = {
        claim_type: newClaimType,
        claim_text: newClaimText.trim(),
        extraction_method: "manual",
      };

      await api.addClaim(matterId, token, claim);
      toast.success(`${newClaimType === "allegation" ? "Allegation" : "Defense"} added successfully`);
      setAddClaimDialogOpen(false);
      setNewClaimText("");
      mutate();
    } catch (error: any) {
      toast.error(`Failed to add claim: ${error.message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteClaim = async (claimId: number, claimType: ClaimType) => {
    if (!token) return;

    try {
      await api.deleteClaim(matterId, claimId, token);
      toast.success(`${claimType === "allegation" ? "Allegation" : "Defense"} deleted`);
      mutate();
    } catch (error: any) {
      toast.error(`Failed to delete claim: ${error.message}`);
    }
  };

  const renderClaimTable = (
    claims: CaseClaimWithWitnesses[],
    type: ClaimType,
    title: string,
    color: string
  ) => (
    <Card className="mb-6">
      <CardHeader className={`bg-${color}-50 dark:bg-${color}-950/20`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {type === "allegation" ? (
              <AlertCircle className={`h-5 w-5 text-${color}-600`} />
            ) : (
              <Shield className={`h-5 w-5 text-${color}-600`} />
            )}
            <CardTitle className={`text-${color}-700 dark:text-${color}-400`}>
              {title}
            </CardTitle>
          </div>
          <Badge variant="secondary">{claims.length}</Badge>
        </div>
        <CardDescription>
          {type === "allegation"
            ? "Claims made by the plaintiff against the defendant"
            : "Defenses raised by the defendant"}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-4">
        {claims.length === 0 ? (
          <p className="text-muted-foreground text-center py-4">
            No {type === "allegation" ? "allegations" : "defenses"} added yet.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">#</TableHead>
                <TableHead>Claim</TableHead>
                <TableHead>Linked Witnesses</TableHead>
                <TableHead className="w-24">Status</TableHead>
                <TableHead className="w-12"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {claims.map((claim) => (
                <TableRow key={claim.id}>
                  <TableCell className="font-medium">{claim.claim_number}</TableCell>
                  <TableCell className="max-w-md">
                    <p className="line-clamp-2">{claim.claim_text}</p>
                  </TableCell>
                  <TableCell>
                    {claim.linked_witnesses && claim.linked_witnesses.length > 0 ? (
                      <div className="space-y-1">
                        {claim.linked_witnesses.slice(0, 3).map((w, idx) => (
                          <div key={idx} className="flex items-center gap-1">
                            <Badge
                              variant={
                                w.relationship === "supports"
                                  ? "default"
                                  : w.relationship === "undermines"
                                  ? "destructive"
                                  : "secondary"
                              }
                              className="text-xs"
                            >
                              {w.relationship}
                            </Badge>
                            <span className="text-sm">{w.witness_name}</span>
                          </div>
                        ))}
                        {claim.linked_witnesses.length > 3 && (
                          <span className="text-xs text-muted-foreground">
                            +{claim.linked_witnesses.length - 3} more
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-muted-foreground text-sm">No witnesses linked</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {claim.is_verified ? (
                      <Badge variant="outline" className="gap-1">
                        <CheckCircle className="h-3 w-3" />
                        Verified
                      </Badge>
                    ) : (
                      <Badge variant="secondary">Unverified</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDeleteClaim(claim.id, type)}
                    >
                      <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" onClick={() => router.back()}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
        <Card>
          <CardContent className="py-8 text-center">
            <AlertCircle className="mx-auto h-12 w-12 text-destructive mb-4" />
            <p className="text-lg font-medium">Failed to load relevancy data</p>
            <p className="text-muted-foreground">{error.message}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" onClick={() => router.back()}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Relevancy Analysis</h1>
            <p className="text-muted-foreground">
              Manage allegations, defenses, and witness relationships
            </p>
          </div>
        </div>
        <Button onClick={() => setAddClaimDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add Claim
        </Button>
      </div>

      {/* Allegations */}
      {renderClaimTable(
        relevancy?.allegations || [],
        "allegation",
        "Allegations",
        "red"
      )}

      {/* Defenses */}
      {renderClaimTable(
        relevancy?.defenses || [],
        "defense",
        "Defenses",
        "green"
      )}

      {/* Witness Summary */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            <CardTitle>Witness Relevancy Summary</CardTitle>
          </div>
          <CardDescription>
            Overview of how witnesses relate to case claims
          </CardDescription>
        </CardHeader>
        <CardContent>
          {relevancy?.witness_summary && relevancy.witness_summary.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Witness</TableHead>
                  <TableHead>Relevant To</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {relevancy.witness_summary.map((witness) => (
                  <TableRow key={witness.witness_id}>
                    <TableCell className="font-medium">{witness.name}</TableCell>
                    <TableCell>
                      {witness.claim_links.length > 0 ? (
                        <div className="space-y-1">
                          {witness.claim_links.map((link, idx) => (
                            <div key={idx} className="flex items-center gap-2">
                              <Badge
                                variant={link.claim_type === "allegation" ? "destructive" : "default"}
                                className="text-xs"
                              >
                                {link.claim_type === "allegation" ? "Alleg" : "Def"} #{link.claim_number}
                              </Badge>
                              <Badge
                                variant={
                                  link.relationship === "supports"
                                    ? "default"
                                    : link.relationship === "undermines"
                                    ? "destructive"
                                    : "secondary"
                                }
                                className="text-xs"
                              >
                                {link.relationship}
                              </Badge>
                              {link.explanation && (
                                <span className="text-sm text-muted-foreground truncate max-w-xs">
                                  {link.explanation}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">No claim links</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-muted-foreground text-center py-4">
              No witness relevancy data available yet.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Unlinked Witnesses */}
      {relevancy?.unlinked_witnesses && relevancy.unlinked_witnesses.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-amber-600">Unlinked Witnesses</CardTitle>
            <CardDescription>
              These witnesses have not been linked to any claims yet
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {relevancy.unlinked_witnesses.map((witness) => (
                <Badge key={witness.id} variant="outline">
                  {witness.full_name} ({witness.role})
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Add Claim Dialog */}
      <Dialog open={addClaimDialogOpen} onOpenChange={setAddClaimDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Claim</DialogTitle>
            <DialogDescription>
              Add an allegation or defense to the case.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Claim Type</label>
              <Select
                value={newClaimType}
                onValueChange={(v) => setNewClaimType(v as ClaimType)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="allegation">Allegation</SelectItem>
                  <SelectItem value="defense">Defense</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Claim Text</label>
              <Textarea
                placeholder="Enter the claim text..."
                value={newClaimText}
                onChange={(e) => setNewClaimText(e.target.value)}
                rows={4}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAddClaimDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddClaim} disabled={isSubmitting || !newClaimText.trim()}>
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Add Claim
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
