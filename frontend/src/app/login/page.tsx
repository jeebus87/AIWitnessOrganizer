"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Users, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuthStore } from "@/store/auth";
import { toast } from "sonner";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, token, isLoading, isHydrated } = useAuthStore();

  // Show error from URL params (e.g., from failed OAuth)
  useEffect(() => {
    const error = searchParams.get("error");
    if (error) {
      toast.error(error);
    }
  }, [searchParams]);

  // Redirect if already logged in
  useEffect(() => {
    if (isHydrated && token) {
      router.push("/matters");
    }
  }, [isHydrated, token, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background to-muted p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Users className="h-6 w-6 text-primary" />
          </div>
          <CardTitle className="text-2xl">AI Witness Finder</CardTitle>
          <CardDescription>
            Automated Legal Witness Extraction System
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <p className="text-center text-sm text-muted-foreground">
            Sign in with your Clio account to get started. Your matters and
            documents will be synced automatically.
          </p>
          <Button
            className="w-full"
            size="lg"
            onClick={login}
            disabled={isLoading}
          >
            {isLoading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <svg
                className="mr-2 h-5 w-5"
                viewBox="0 0 24 24"
                fill="currentColor"
              >
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
              </svg>
            )}
            Sign in with Clio
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            By signing in, you agree to allow AI Witness Finder to access your
            Clio matters and documents for witness extraction.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
