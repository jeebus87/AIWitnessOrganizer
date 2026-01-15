"use client";

import { CheckCircle2, FileText, Lock, RefreshCw, Search, Zap } from "lucide-react";

const features = [
    {
        name: "Seamless Clio Integration",
        description: "Connect your Clio account in seconds. We automatically sync your matters and documents.",
        icon: RefreshCw,
    },
    {
        name: "AI-Powered Extraction",
        description: "Our advanced AI analyzes thousands of pages to identify potential witnesses and their context.",
        icon: Search,
    },
    {
        name: "Instant Summaries",
        description: "Get concise summaries of every witness's involvement without reading every document.",
        icon: FileText,
    },
    {
        name: "Enterprise Security",
        description: "Your data is encrypted at rest and in transit. We prioritize client confidentiality.",
        icon: Lock,
    },
    {
        name: "Lightning Fast",
        description: "Process gigabytes of discovery documents in minutes, not days. Save hours of billable time.",
        icon: Zap,
    },
    {
        name: "Smart Categorization",
        description: "Witnesses are automatically categorized by their role and relevance to the case.",
        icon: CheckCircle2,
    },
];

export function Features() {
    return (
        <section id="features" className="py-24 bg-muted/30">
            <div className="container mx-auto px-4">
                <div className="text-center max-w-3xl mx-auto mb-16">
                    <h2 className="text-3xl font-bold tracking-tight mb-4">
                        Everything you need to master discovery
                    </h2>
                    <p className="text-lg text-muted-foreground">
                        Stop searching manually through boxes of documents. Let AI handle the grunt work while you focus on case strategy.
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
                    {features.map((feature) => (
                        <div
                            key={feature.name}
                            className="p-6 rounded-2xl bg-card border shadow-sm hover:shadow-md transition-shadow group"
                        >
                            <div className="w-12 h-12 rounded-lg bg-blue-500/10 flex items-center justify-center mb-6 group-hover:bg-blue-500/20 transition-colors">
                                <feature.icon className="h-6 w-6 text-blue-600 dark:text-blue-400" />
                            </div>
                            <h3 className="text-xl font-semibold mb-3">{feature.name}</h3>
                            <p className="text-muted-foreground leading-relaxed">
                                {feature.description}
                            </p>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
