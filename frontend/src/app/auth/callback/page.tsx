"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/store/auth";
import { Loader2 } from "lucide-react";

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setToken, fetchUserProfile, setLoading } = useAuthStore();

  useEffect(() => {
    const token = searchParams.get("token");
    const error = searchParams.get("error");

    if (error) {
      router.push(`/login?error=${encodeURIComponent(error)}`);
      return;
    }

    if (token) {
      setLoading(true);
      setToken(token);
      fetchUserProfile().then(() => {
        setLoading(false);
        router.push("/matters");
      }).catch(() => {
        setLoading(false);
        router.push("/login?error=Failed to fetch user profile");
      });
    } else {
      router.push("/login?error=No token received");
    }
  }, [searchParams, setToken, fetchUserProfile, setLoading, router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-muted-foreground">Completing login...</p>
      </div>
    </div>
  );
}
