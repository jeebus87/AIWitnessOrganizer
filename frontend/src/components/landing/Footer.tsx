"use client";

import Link from "next/link";

export function Footer() {
    return (
        <footer className="bg-muted py-12 border-t">
            <div className="container mx-auto px-4">
                <div className="flex flex-col md:flex-row justify-between items-center gap-6">
                    <div className="flex items-center space-x-2">
                        <span className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-400 dark:to-indigo-400">
                            AI Witness Organizer
                        </span>
                    </div>

                    <div className="flex gap-8 text-sm text-muted-foreground">
                        <Link href="/terms" className="hover:text-foreground transition-colors">
                            Terms
                        </Link>
                        <Link href="/privacy" className="hover:text-foreground transition-colors">
                            Privacy
                        </Link>
                        <Link href="mailto:support@juridionlaw.com" className="hover:text-foreground transition-colors">
                            Contact
                        </Link>
                    </div>

                    <div className="flex flex-col sm:flex-row gap-2 text-sm text-muted-foreground">
                        <p>© {new Date().getFullYear()} Juridion LLC. All rights reserved.</p>
                        <p className="hidden sm:block">•</p>
                        <p>A product by <span className="font-medium">Juridion LLC</span></p>
                    </div>
                </div>
            </div>
        </footer>
    );
}
