"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AppSidebar } from "@/components/app-sidebar";
import { HelpChatbot } from "@/components/help-chatbot";
import { SyncOverlay } from "@/components/sync-overlay";
import { DemoModal, useDemoModal } from "@/components/onboarding/demo-modal";
import { useAuthStore } from "@/store/auth";

export default function AuthenticatedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { token, isLoading, isHydrated } = useAuthStore();
  const { showDemo, setShowDemo, openDemo, markComplete } = useDemoModal();

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
      {/* Demo Modal */}
      <DemoModal
        open={showDemo}
        onOpenChange={setShowDemo}
        onComplete={markComplete}
      />

      <SyncOverlay />
      <div className="flex h-screen">
        <AppSidebar onViewDemo={openDemo} />
        <main className="flex-1 overflow-auto bg-muted/30">
          <div className="p-6">{children}</div>
        </main>
        <HelpChatbot />
      </div>
    </>
  );
}
