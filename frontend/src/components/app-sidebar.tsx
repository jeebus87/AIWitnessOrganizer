"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FileText,
  Users,
  Briefcase,
  Settings,
  LogOut,
  Loader2,
  Building2,
  CreditCard,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuthStore } from "@/store/auth";

const navigation = [
  { name: "Matters", href: "/matters", icon: Briefcase },
  { name: "Witnesses", href: "/witnesses", icon: Users },
  { name: "Jobs", href: "/jobs", icon: FileText },
  { name: "Settings", href: "/settings", icon: Settings },
];

// Format subscription tier for display
function formatTier(tier: string | undefined): string {
  if (!tier || tier === "free") return "Free";
  if (tier === "firm") return "Firm Plan";
  return tier.charAt(0).toUpperCase() + tier.slice(1);
}

// Get tier badge color
function getTierColor(tier: string | undefined): string {
  if (!tier || tier === "free") return "secondary";
  if (tier === "firm" || tier === "active") return "default";
  return "secondary";
}

export function AppSidebar() {
  const pathname = usePathname();
  const { userProfile, logout, isLoading } = useAuthStore();

  const handleLogout = () => {
    logout();
  };

  // Get firm name from organization or fall back to user name
  const firmName = userProfile?.organization?.name || userProfile?.display_name || "My Firm";
  const subscriptionTier = userProfile?.organization?.subscription_tier || "free";
  const isAdmin = userProfile?.is_admin || false;

  return (
    <div className="flex h-full w-64 flex-col border-r bg-background">
      {/* App Logo/Name */}
      <div className="flex h-16 items-center border-b px-4">
        <Link href="/matters" className="flex items-center gap-2 font-semibold">
          <Users className="h-6 w-6 text-primary" />
          <span>AI Witness Organizer</span>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 p-4">
        {navigation.map((item) => {
          const isActive = pathname.startsWith(item.href);
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <item.icon className="h-5 w-5" />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* User/Firm Section */}
      <div className="border-t p-4">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="w-full justify-start gap-2 h-auto py-2">
              <Avatar className="h-8 w-8">
                <AvatarFallback className="bg-primary/10 text-primary">
                  {isLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Building2 className="h-4 w-4" />
                  )}
                </AvatarFallback>
              </Avatar>
              <div className="flex flex-col items-start text-sm overflow-hidden">
                <span className="font-medium truncate max-w-[140px]">
                  {firmName}
                </span>
                <div className="flex items-center gap-1">
                  <Badge
                    variant={getTierColor(subscriptionTier) as "default" | "secondary"}
                    className="text-[10px] px-1.5 py-0"
                  >
                    {formatTier(subscriptionTier)}
                  </Badge>
                  {isAdmin && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                      Admin
                    </Badge>
                  )}
                </div>
              </div>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <div className="px-2 py-1.5 text-sm">
              <p className="font-medium">{userProfile?.display_name || "User"}</p>
              <p className="text-xs text-muted-foreground">{userProfile?.email}</p>
            </div>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href="/settings">
                <Settings className="mr-2 h-4 w-4" />
                Settings
              </Link>
            </DropdownMenuItem>
            {isAdmin && (
              <DropdownMenuItem asChild>
                <Link href="/settings?tab=billing">
                  <CreditCard className="mr-2 h-4 w-4" />
                  Billing
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout}>
              <LogOut className="mr-2 h-4 w-4" />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
