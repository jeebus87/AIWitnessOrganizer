"use client";

import { Suspense, useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { useSyncStore } from "@/store/sync";
import { api } from "@/lib/api";
import { Loader2, CheckCircle2, XCircle, Shield, Database, Lock, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

type CallbackState = "consent" | "loading" | "success" | "error";

async function waitForSyncComplete(token: string, maxWaitMs: number = 60000): Promise<void> {
  const pollInterval = 2000;
  const startTime = Date.now();
  while (Date.now() - startTime < maxWaitMs) {
    try {
      const status = await api.getSyncStatus(token);
      if (!status.is_syncing) return;
    } catch (error) {
      console.error("Error checking sync status:", error);
    }
    await new Promise(resolve => setTimeout(resolve, pollInterval));
  }
}

function AuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setToken, fetchUserProfile, setLoading } = useAuthStore();
  const { startSync, endSync } = useSyncStore();
  const [state, setState] = useState<CallbackState>("consent");
  const [error, setError] = useState<string | null>(null);
  const [consentChecked, setConsentChecked] = useState(false);
  const [authToken, setAuthToken] = useState<string | null>(null);

  const handleCallback = useCallback(async (token: string) => {
    try {
      setState("loading");
      setLoading(true);
      setToken(token);
      await fetchUserProfile();
      setLoading(false);
      startSync("Syncing matters from Clio");
      try { await api.syncMatters(token); } catch (e) { console.error(e); }
      endSync();
      setState("success");
      setTimeout(() => router.push("/matters"), 1500);
    } catch (err) {
      setLoading(false);
      setState("error");
      setError(err instanceof Error ? err.message : "Failed");
    }
  }, [router, setToken, fetchUserProfile, setLoading, startSync, endSync]);

  useEffect(() => {
    const token = searchParams.get("token");
    const errorParam = searchParams.get("error");
    if (errorParam) { setState("error"); setError(errorParam); return; }
    if (!token) { setState("error"); setError("No token"); return; }
    setAuthToken(token);
    setState("consent");
  }, [searchParams]);

  const handleConsent = () => { if (authToken && consentChecked) handleCallback(authToken); };

  return (
    <>
      {state === "consent" && (
        <div className="bg-card border border-border p-8 rounded-xl max-w-lg shadow-lg">
          <div className="flex items-center justify-center mb-6">
            <div className="h-14 w-14 rounded-full bg-blue-500/10 flex items-center justify-center">
              <Shield className="h-7 w-7 text-blue-500" />
            </div>
          </div>
          <h2 className="text-xl font-semibold mb-2 text-center">Data Privacy & Security</h2>
          <p className="text-muted-foreground text-sm text-center mb-6">Before connecting your Clio account, please review how we handle your data.</p>
          <div className="space-y-4 mb-6 text-left">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50">
              <Database className="h-5 w-5 text-blue-500 mt-0.5 flex-shrink-0" />
              <div><h4 className="font-medium text-sm">Data We Access</h4><p className="text-xs text-muted-foreground">Case documents and matter information from Clio to extract witness information.</p></div>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50">
              <Eye className="h-5 w-5 text-blue-500 mt-0.5 flex-shrink-0" />
              <div><h4 className="font-medium text-sm">AI-Powered Extraction</h4><p className="text-xs text-muted-foreground">We use AI to extract witness info. <strong>All data should be verified.</strong></p></div>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/50">
              <Lock className="h-5 w-5 text-blue-500 mt-0.5 flex-shrink-0" />
              <div><h4 className="font-medium text-sm">Your Data Stays Private</h4><p className="text-xs text-muted-foreground">Data encrypted. <strong>Zero Data Retention</strong> with AI providers.</p></div>
            </div>
          </div>
          <div className="flex items-start gap-3 p-4 rounded-lg border mb-6">
            <Checkbox id="consent" checked={consentChecked} onCheckedChange={(c) => setConsentChecked(c === true)} />
            <label htmlFor="consent" className="text-sm cursor-pointer">
              I have read and agree to the{" "}
              <a href="/privacy" target="_blank" className="text-blue-500 hover:underline">Privacy Policy</a>{" "}
              and{" "}
              <a href="/terms" target="_blank" className="text-blue-500 hover:underline">Terms of Service</a>.
            </label>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" className="flex-1" onClick={() => router.replace("/login")}>Cancel</Button>
            <Button className="flex-1" onClick={handleConsent} disabled={!consentChecked}>Continue</Button>
          </div>
        </div>
      )}
      {state === "loading" && (<div className="bg-card p-12 rounded-xl"><Loader2 className="h-12 w-12 text-blue-500 mx-auto mb-4 animate-spin" /><h2 className="text-xl font-semibold mb-2">Connecting...</h2></div>)}
      {state === "success" && (<div className="bg-card p-12 rounded-xl"><CheckCircle2 className="h-12 w-12 text-green-500 mx-auto mb-4" /><h2 className="text-xl font-semibold mb-2">Connected!</h2></div>)}
      {state === "error" && (<div className="bg-card p-12 rounded-xl"><XCircle className="h-12 w-12 text-destructive mx-auto mb-4" /><h2 className="text-xl font-semibold mb-2">Failed</h2><p className="mb-6">{error}</p><Button onClick={() => router.replace("/login")} variant="outline">Try Again</Button></div>)}
    </>
  );
}

export default function AuthCallbackPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-6">
      <div className="w-full max-w-lg text-center">
        <div className="flex items-center justify-center gap-2 mb-8">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700" />
          <span className="text-2xl font-semibold">AI Witness Organizer</span>
        </div>
        <Suspense fallback={<div className="p-12"><Loader2 className="h-12 w-12 animate-spin mx-auto" /></div>}>
          <AuthCallbackContent />
        </Suspense>
      </div>
    </div>
  );
}