"use client";

import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/store/auth";
import { CheckCircle2, ArrowRight, FileText, Search, Users } from "lucide-react";
import Link from "next/link";

export function Hero() {
    const { login } = useAuthStore();

    return (
        <section className="relative pt-32 pb-20 lg:pt-48 lg:pb-32 overflow-hidden">
            {/* Background gradients */}
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full h-full max-w-7xl pointer-events-none">
                <div className="absolute top-0 left-1/4 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl mix-blend-multiply animate-blob" />
                <div className="absolute top-0 right-1/4 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl mix-blend-multiply animate-blob animation-delay-2000" />
            </div>

            <div className="container mx-auto px-4 relative z-10">
                <div className="text-center max-w-4xl mx-auto mb-16">
                    <div className="inline-flex items-center px-3 py-1 rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400 text-sm font-medium mb-8">
                        <span className="flex w-2 h-2 rounded-full bg-blue-600 dark:bg-blue-400 mr-2" />
                        Powered by Claude 4.5 Sonnet
                    </div>

                    <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-8">
                        Legal Witness Extraction,{" "}
                        <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600 dark:from-blue-400 dark:to-indigo-400">
                            Simplified
                        </span>
                    </h1>

                    <p className="text-xl text-muted-foreground mb-10 max-w-2xl mx-auto leading-relaxed">
                        Automate the tedious process of finding witnesses in discovery documents.
                        Connects seamlessly with Clio to analyze PDFs, Word, Excel, emails, and more in seconds.
                    </p>

                    <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                        <Button
                            size="lg"
                            onClick={login}
                            className="h-12 px-8 text-lg rounded-full"
                        >
                            Start Free Trial
                            <ArrowRight className="ml-2 h-4 w-4" />
                        </Button>
                        <Link href="#features">
                            <Button
                                variant="outline"
                                size="lg"
                                className="h-12 px-8 text-lg rounded-full"
                            >
                                How it Works
                            </Button>
                        </Link>
                    </div>

                    <div className="mt-12 flex items-center justify-center gap-8 text-sm text-muted-foreground">
                        <div className="flex items-center gap-2">
                            <CheckCircle2 className="h-4 w-4 text-green-500" />
                            <span>No credit card required</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <CheckCircle2 className="h-4 w-4 text-green-500" />
                            <span>Clio Certified Integration</span>
                        </div>
                    </div>
                </div>

                {/* Dashboard Preview Mockup */}
                <div className="relative mx-auto max-w-5xl rounded-xl border bg-background/50 backdrop-blur shadow-2xl overflow-hidden aspect-[16/9] group">
                    <div className="absolute inset-0 bg-gradient-to-tr from-blue-500/5 to-indigo-500/5" />

                    {/* Abstract UI Representation since we don't have a real screenshot handy */}
                    <div className="p-8 h-full flex flex-col">
                        <div className="flex items-center gap-4 mb-8 border-b pb-4">
                            <div className="w-48 h-8 bg-muted rounded animate-pulse" />
                            <div className="flex-1" />
                            <div className="w-8 h-8 bg-blue-100 dark:bg-blue-900 rounded-full" />
                        </div>

                        <div className="grid grid-cols-12 gap-8 flex-1">
                            {/* Sidebar */}
                            <div className="col-span-3 space-y-4">
                                <div className="h-10 w-full bg-blue-50 dark:bg-blue-900/20 rounded border border-blue-100 dark:border-blue-800" />
                                <div className="h-10 w-full bg-muted/50 rounded" />
                                <div className="h-10 w-full bg-muted/50 rounded" />
                            </div>

                            {/* Main Content */}
                            <div className="col-span-9 space-y-6">
                                <div className="grid grid-cols-3 gap-4">
                                    {[FileText, Search, Users].map((Icon, i) => (
                                        <div key={i} className="p-4 rounded-xl border bg-card/50">
                                            <Icon className="h-6 w-6 text-blue-500 mb-2" />
                                            <div className="h-4 w-24 bg-muted rounded mb-2" />
                                            <div className="h-8 w-12 bg-muted rounded" />
                                        </div>
                                    ))}
                                </div>
                                <div className="flex-1 bg-muted/20 rounded-xl border border-dashed border-muted p-8 flex items-center justify-center">
                                    <div className="text-center space-y-4">
                                        <div className="w-16 h-16 bg-blue-100 dark:bg-blue-900/50 rounded-full mx-auto flex items-center justify-center">
                                            <Search className="h-8 w-8 text-blue-500" />
                                        </div>
                                        <div className="text-muted-foreground">AI Processing in progress...</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}
