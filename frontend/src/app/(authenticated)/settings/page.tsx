"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ExternalLink, CheckCircle, Edit2, Save, X, CreditCard, Loader2, RefreshCw, Link2Off } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/store/auth";
import { useSyncStore } from "@/store/sync";
import { api } from "@/lib/api";
import { toast } from "sonner";

// Top-up packages
const TOPUP_PACKAGES = [
  { id: "small", credits: 10, price: "$4.99", perCredit: "$0.50" },
  { id: "medium", credits: 25, price: "$12.49", perCredit: "$0.50" },
  { id: "large", credits: 50, price: "$24.99", perCredit: "$0.50" },
];

export default function SettingsPage() {
  const router = useRouter();
  const { userProfile, token, fetchUserProfile, logout } = useAuthStore();
  const { startSync, endSync } = useSyncStore();
  const [isEditingFirmName, setIsEditingFirmName] = useState(false);
  const [firmName, setFirmName] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [credits, setCredits] = useState<{
    daily_remaining: number;
    bonus_remaining: number;
    is_paid: boolean;
    unlimited: boolean;
  } | null>(null);

  const isAdmin = userProfile?.is_admin || false;
  const organization = userProfile?.organization;

  // Fetch credits on mount
  useEffect(() => {
    const fetchCredits = async () => {
      if (!token) return;
      try {
        const api = await import("@/lib/api").then((m) => m.api);
        const data = await api.getCredits(token);
        setCredits(data);
      } catch (e) {
        console.error("Failed to fetch credits:", e);
      }
    };
    fetchCredits();
  }, [token]);

  // Initialize firm name
  useEffect(() => {
    if (organization?.name) {
      setFirmName(organization.name);
    }
  }, [organization?.name]);

  const handleSaveFirmName = async () => {
    if (!token || !firmName.trim()) return;
    setIsSaving(true);
    try {
      const api = await import("@/lib/api").then((m) => m.api);
      await api.updateOrganizationName(token, firmName.trim());
      await fetchUserProfile();
      setIsEditingFirmName(false);
      toast.success("Firm name updated");
    } catch (e) {
      console.error(e);
      toast.error("Failed to update firm name");
    } finally {
      setIsSaving(false);
    }
  };

  const handlePortal = async () => {
    if (!token) return;
    try {
      const api = await import("@/lib/api").then((m) => m.api);
      const { url } = await api.createPortalSession(token);
      window.location.href = url;
    } catch (e) {
      console.error(e);
      toast.error("Failed to access billing portal");
    }
  };

  const handleSubscribe = async () => {
    if (!token) return;
    try {
      const api = await import("@/lib/api").then((m) => m.api);
      const userCount = organization?.user_count || 1;
      const { url } = await api.createSubscriptionCheckout(token, userCount);
      window.location.href = url;
    } catch (e) {
      console.error(e);
      toast.error("Failed to start checkout");
    }
  };

  const handleTopup = async (packageId: string) => {
    if (!token || !isAdmin) return;
    try {
      const api = await import("@/lib/api").then((m) => m.api);
      const { url } = await api.createTopupCheckout(token, packageId);
      window.location.href = url;
    } catch (e) {
      console.error(e);
      toast.error("Failed to start checkout");
    }
  };

  const handleSync = async () => {
    if (!token) return;
    setSyncing(true);
    startSync("Syncing matters from Clio");
    try {
      const result = await api.syncMatters(token);
      toast.success(`Synced ${result.matters_synced} matters from Clio`);

      // Check if any documents are still syncing in the background
      const status = await api.getSyncStatus(token);
      if (status.is_syncing) {
        // Wait for background sync to complete (max 60 seconds)
        const maxWait = 60000;
        const pollInterval = 2000;
        const startTime = Date.now();

        while (Date.now() - startTime < maxWait) {
          await new Promise(resolve => setTimeout(resolve, pollInterval));
          const currentStatus = await api.getSyncStatus(token);
          if (!currentStatus.is_syncing) break;
        }
      }
    } catch (error: unknown) {
      console.error("Sync error:", error);
      const errorMessage = error instanceof Error ? error.message : "Unknown error";
      toast.error(`Sync failed: ${errorMessage}`);
    } finally {
      setSyncing(false);
      endSync();
    }
  };

  const handleReconnectClio = async () => {
    if (!token) return;

    const confirmed = window.confirm(
      "This will disconnect your Clio account and require you to sign in again. " +
      "Use this if you need to update your Clio permissions (e.g., to enable document uploads).\n\n" +
      "Continue?"
    );

    if (!confirmed) return;

    setReconnecting(true);
    try {
      await api.disconnectClio(token);
      toast.success("Clio disconnected. Redirecting to sign in...");
      logout();
      router.push("/login?message=Please+sign+in+again+to+reconnect+Clio+with+updated+permissions");
    } catch (e) {
      console.error(e);
      toast.error("Failed to disconnect Clio");
      setReconnecting(false);
    }
  };

  const isPaidPlan = organization?.subscription_tier === "firm" || organization?.subscription_status === "active";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Manage your firm and billing settings
        </p>
      </div>

      <div className="grid gap-6">
        {/* Firm Information */}
        <Card>
          <CardHeader>
            <CardTitle>Firm Information</CardTitle>
            <CardDescription>Your law firm details</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <div className="text-sm font-medium">Firm Name</div>
              {isEditingFirmName ? (
                <div className="flex items-center gap-2">
                  <Input
                    value={firmName}
                    onChange={(e) => setFirmName(e.target.value)}
                    className="max-w-xs"
                    placeholder="Enter firm name"
                  />
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={handleSaveFirmName}
                    disabled={isSaving}
                  >
                    {isSaving ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => {
                      setIsEditingFirmName(false);
                      setFirmName(organization?.name || "");
                    }}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">
                    {organization?.name || "Not set"}
                  </span>
                  {isAdmin && (
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6"
                      onClick={() => setIsEditingFirmName(true)}
                    >
                      <Edit2 className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              )}
            </div>
            <Separator />
            <div className="grid gap-2">
              <div className="text-sm font-medium">Your Name</div>
              <div className="text-muted-foreground">
                {userProfile?.display_name || "Not set"}
              </div>
            </div>
            <Separator />
            <div className="grid gap-2">
              <div className="text-sm font-medium">Email</div>
              <div className="text-muted-foreground">{userProfile?.email || "—"}</div>
            </div>
            <Separator />
            <div className="grid gap-2">
              <div className="text-sm font-medium">Role</div>
              <div>
                <Badge variant={isAdmin ? "default" : "secondary"}>
                  {isAdmin ? "Admin" : "Member"}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Clio Integration */}
        <Card>
          <CardHeader>
            <CardTitle>Clio Integration</CardTitle>
            <CardDescription>
              Your Clio account is connected through sign-in
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-500/10">
                  <svg
                    className="h-6 w-6 text-blue-500"
                    viewBox="0 0 24 24"
                    fill="currentColor"
                  >
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
                  </svg>
                </div>
                <div>
                  <div className="font-medium">Clio Manage</div>
                  <div className="text-sm text-muted-foreground">
                    Legal practice management software
                  </div>
                </div>
              </div>
              <Badge variant="outline" className="text-green-500 border-green-500">
                <CheckCircle className="mr-1 h-3 w-3" />
                Connected
              </Badge>
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">Sync Data</div>
                <div className="text-sm text-muted-foreground">
                  Pull latest matters and documents from Clio
                </div>
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
            <Separator />
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">Reconnect Clio</div>
                <div className="text-sm text-muted-foreground">
                  Reauthorize if permissions need updating (e.g., to enable document uploads)
                </div>
              </div>
              <Button variant="outline" onClick={handleReconnectClio} disabled={reconnecting}>
                {reconnecting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Link2Off className="mr-2 h-4 w-4" />
                )}
                Reconnect
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Report Credits */}
        <Card>
          <CardHeader>
            <CardTitle>Report Credits</CardTitle>
            <CardDescription>
              Credits are used when generating witness reports
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-lg border p-4">
                <div className="text-2xl font-bold">
                  {credits?.unlimited ? "∞" : credits?.daily_remaining ?? "—"}
                </div>
                <div className="text-sm text-muted-foreground">
                  {credits?.unlimited ? "Unlimited (Firm Plan)" : "Daily Credits Remaining"}
                </div>
              </div>
              <div className="rounded-lg border p-4">
                <div className="text-2xl font-bold">
                  {organization?.bonus_credits ?? credits?.bonus_remaining ?? 0}
                </div>
                <div className="text-sm text-muted-foreground">
                  Bonus Credits
                </div>
              </div>
            </div>

            {!isPaidPlan && (
              <div className="text-sm text-muted-foreground">
                Free plan includes {10} reports per user per day. Upgrade to Firm Plan for unlimited reports.
              </div>
            )}

            {/* Top-up Section (Admin only) */}
            {isAdmin && (
              <>
                <Separator />
                <div>
                  <div className="font-medium mb-3">Buy More Credits</div>
                  <div className="grid grid-cols-3 gap-3">
                    {TOPUP_PACKAGES.map((pkg) => (
                      <button
                        key={pkg.id}
                        onClick={() => handleTopup(pkg.id)}
                        className="rounded-lg border p-3 text-center hover:border-primary hover:bg-primary/5 transition-colors"
                      >
                        <div className="text-lg font-bold">{pkg.credits}</div>
                        <div className="text-xs text-muted-foreground">credits</div>
                        <div className="text-sm font-medium mt-1">{pkg.price}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Subscription */}
        <Card>
          <CardHeader>
            <CardTitle>Subscription</CardTitle>
            <CardDescription>
              Manage your firm&apos;s subscription and billing
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-medium capitalize flex items-center gap-2">
                    {isPaidPlan ? "Firm Plan" : "Free Plan"}
                    <Badge variant={isPaidPlan ? "default" : "secondary"}>
                      {organization?.subscription_status || "free"}
                    </Badge>
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {isPaidPlan
                      ? `${organization?.user_count || 1} user(s) • $29.99/user/month`
                      : "10 reports per user per day"}
                  </div>
                  {organization?.current_period_end && isPaidPlan && (
                    <div className="text-xs text-muted-foreground mt-1">
                      Renews: {new Date(organization.current_period_end).toLocaleDateString()}
                    </div>
                  )}
                </div>
                {isAdmin && (
                  <>
                    {isPaidPlan ? (
                      <Button variant="outline" onClick={handlePortal}>
                        <ExternalLink className="mr-2 h-4 w-4" />
                        Manage Billing
                      </Button>
                    ) : (
                      <Button onClick={handleSubscribe}>
                        <CreditCard className="mr-2 h-4 w-4" />
                        Upgrade to Firm
                      </Button>
                    )}
                  </>
                )}
              </div>
            </div>
            {!isAdmin && (
              <div className="text-sm text-muted-foreground">
                Contact your firm administrator to manage billing.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
