"use client";

import { useState } from "react";
import { Link2, Link2Off, ExternalLink, CheckCircle, Loader2 } from "lucide-react";
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
import { useAuthStore } from "@/store/auth";
import { api } from "@/lib/api";
import { toast } from "sonner";

export default function SettingsPage() {
  const { user, userProfile, fetchUserProfile, token } = useAuthStore();
  const [disconnecting, setDisconnecting] = useState(false);

  const handleDisconnectClio = async () => {
    if (!token) return;
    setDisconnecting(true);
    try {
      // This would call an API endpoint to disconnect Clio
      toast.success("Clio disconnected successfully");
      await fetchUserProfile();
    } catch (error) {
      toast.error("Failed to disconnect Clio");
      console.error(error);
    } finally {
      setDisconnecting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Manage your account and integrations
        </p>
      </div>

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <CardDescription>Your account information</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2">
              <div className="text-sm font-medium">Email</div>
              <div className="text-muted-foreground">{user?.email || "—"}</div>
            </div>
            <Separator />
            <div className="grid gap-2">
              <div className="text-sm font-medium">Display Name</div>
              <div className="text-muted-foreground">
                {userProfile?.display_name || user?.displayName || "Not set"}
              </div>
            </div>
            <Separator />
            <div className="grid gap-2">
              <div className="text-sm font-medium">Subscription</div>
              <div>
                <Badge variant="secondary" className="capitalize">
                  {userProfile?.subscription_tier || "Free"}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Clio Integration</CardTitle>
            <CardDescription>
              Connect your Clio account to sync matters and documents
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
              {userProfile?.clio_connected ? (
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="text-green-500 border-green-500">
                    <CheckCircle className="mr-1 h-3 w-3" />
                    Connected
                  </Badge>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleDisconnectClio}
                    disabled={disconnecting}
                  >
                    {disconnecting ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Link2Off className="mr-2 h-4 w-4" />
                    )}
                    Disconnect
                  </Button>
                </div>
              ) : (
                <Button asChild>
                  <a href={api.getClioAuthUrl()}>
                    <Link2 className="mr-2 h-4 w-4" />
                    Connect Clio
                  </a>
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Subscription</CardTitle>
            <CardDescription>
              Manage your subscription and billing
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-medium capitalize">
                    {userProfile?.subscription_tier || "Free"} Plan
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {userProfile?.subscription_tier === "free"
                      ? "Limited features and processing"
                      : `Full access to all features`}
                  </div>
                </div>
                <Button variant="outline">
                  <ExternalLink className="mr-2 h-4 w-4" />
                  Manage Billing
                </Button>
              </div>
            </div>
            <div className="text-sm text-muted-foreground">
              Need more processing power? Upgrade to a higher tier for unlimited
              document processing and priority support.
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
