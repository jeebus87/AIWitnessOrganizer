"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AppSidebar } from "@/components/app-sidebar";
import { HelpChatbot } from "@/components/help-chatbot";
import { SyncOverlay } from "@/components/sync-overlay";
import { useAuthStore } from "@/store/auth";

export default function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { token, isLoading, isHydrated } = useAuthStore();

  useEffect(() => {
    if (isHydrated && !isLoading && !token) {
      router.push("/login");
    }
  }, [token, isLoading, isHydrated, router]);

  if (!isHydrated || isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground">Loading...</div>
      </div>
    );
  }

  if (!token) {
    return null;
  }

  return (
    <>
      {/* DEBUG: This should always show if layout renders */}
      <div className="fixed top-0 left-0 right-0 bg-red-500 text-white text-center py-2 z-[9999]">
        DEBUG: Layout is rendering - SyncOverlay should work
      </div>
      <SyncOverlay />
      <div className="flex h-screen pt-10">
        <AppSidebar />
        <main className="flex-1 overflow-auto bg-muted/30">
          <div className="p-6">{children}</div>
        </main>
        <HelpChatbot />
      </div>
    </>
  );
}
