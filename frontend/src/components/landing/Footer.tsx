"use client";

import Link from "next/link";

export function Footer() {
    return (
        <footer className="bg-muted py-12 border-t">
            <div className="container mx-auto px-4">
                <div className="flex flex-col md:flex-row justify-between items-center gap-6">
                    <div className="flex items-center space-x-2">
                        <span className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-400 dark:to-indigo-400">
                            AI Witness Finder
                        </span>
                    </div>

                    <div className="flex gap-8 text-sm text-muted-foreground">
                        <Link href="#" className="hover:text-foreground transition-colors">
                            Terms
                        </Link>
                        <Link href="#" className="hover:text-foreground transition-colors">
                            Privacy
                        </Link>
                        <Link href="#" className="hover:text-foreground transition-colors">
                            Contact
                        </Link>
                    </div>

                    <div className="text-sm text-muted-foreground">
                        © {new Date().getFullYear()} AI Witness Finder. All rights reserved.
                    </div>
                </div>
            </div>
        </footer>
    );
}
