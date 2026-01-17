"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/store/auth";
import { useEffect, useState } from "react";

export function Header() {
    const { login, isHydrated, userProfile } = useAuthStore();
    const [scrolled, setScrolled] = useState(false);

    useEffect(() => {
        const handleScroll = () => {
            setScrolled(window.scrollY > 20);
        };
        window.addEventListener("scroll", handleScroll);
        return () => window.removeEventListener("scroll", handleScroll);
    }, []);

    if (!isHydrated) return null;

    return (
        <header
            className={`fixed top-0 w-full z-50 transition-all duration-300 ${scrolled
                    ? "bg-background/80 backdrop-blur-md border-b shadow-sm"
                    : "bg-transparent"
                }`}
        >
            <div className="container mx-auto px-4 h-16 flex items-center justify-between">
                <Link href="/" className="flex items-center space-x-2">
                    <span className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-400 dark:to-indigo-400">
                        AI Witness Organizer
                    </span>
                </Link>

                <nav className="hidden md:flex items-center space-x-8">
                    <Link
                        href="#features"
                        className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
                    >
                        Features
                    </Link>
                    <Link
                        href="#pricing"
                        className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
                    >
                        Pricing
                    </Link>
                </nav>

                <div className="flex items-center space-x-4">
                    {userProfile ? (
                        <Link href="/matters">
                            <Button>Dashboard</Button>
                        </Link>
                    ) : (
                        <Button onClick={login} variant="default" className="font-semibold">
                            Sign In with Clio
                        </Button>
                    )}
                </div>
            </div>
        </header>
    );
}
