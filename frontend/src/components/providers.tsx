"use client";

import { useEffect } from "react";
import { Toaster } from "@/components/ui/sonner";
import { useAuthStore } from "@/store/auth";

export function Providers({ children }: { children: React.ReactNode }) {
  const { isHydrated } = useAuthStore();

  useEffect(() => {
    // Any initialization logic can go here
  }, []);

  if (!isHydrated) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  return (
    <>
      {children}
      <Toaster />
    </>
  );
}
