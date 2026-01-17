"use client";

import { Button } from "@/components/ui/button";
import { Check } from "lucide-react";
import { useAuthStore } from "@/store/auth";

const features = [
    "14-day free trial - no credit card required",
    "Unlimited reports",
    "Unlimited matters",
    "AI-powered witness extraction",
    "Clio integration",
    "PDF & Excel exports",
    "Priority processing",
    "Priority support",
];

export function Pricing() {
    const { login } = useAuthStore();

    return (
        <section id="pricing" className="py-24">
            <div className="container mx-auto px-4">
                <div className="text-center max-w-3xl mx-auto mb-16">
                    <h2 className="text-3xl font-bold tracking-tight mb-4">
                        Simple, Transparent Pricing
                    </h2>
                    <p className="text-lg text-muted-foreground">
                        Start with a 14-day free trial. No hidden fees. Cancel anytime.
                    </p>
                </div>

                <div className="max-w-lg mx-auto">
                    <div className="relative p-8 rounded-3xl border bg-muted/30 border-primary/50 shadow-xl">
                        <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 bg-primary text-primary-foreground text-sm font-medium rounded-full">
                            14-Day Free Trial
                        </div>

                        <div className="text-center mb-8">
                            <h3 className="text-xl font-bold mb-2">Firm Plan</h3>
                            <div className="flex items-baseline justify-center gap-1 mb-4">
                                <span className="text-5xl font-bold">$29.99</span>
                                <span className="text-muted-foreground">/user/month</span>
                            </div>
                            <p className="text-muted-foreground text-sm">
                                Unlimited AI-powered witness extraction for your entire firm.
                            </p>
                        </div>

                        <div className="space-y-4 mb-8">
                            {features.map((feature) => (
                                <div key={feature} className="flex items-center gap-3">
                                    <div className="flex-shrink-0 w-5 h-5 rounded-full bg-green-500/10 flex items-center justify-center">
                                        <Check className="h-3 w-3 text-green-600" />
                                    </div>
                                    <span className="text-sm">{feature}</span>
                                </div>
                            ))}
                        </div>

                        <Button
                            className="w-full rounded-full text-lg py-6"
                            onClick={login}
                        >
                            Start Free Trial
                        </Button>

                        <p className="text-center text-xs text-muted-foreground mt-4">
                            No credit card required to start your trial
                        </p>
                    </div>
                </div>
            </div>
        </section>
    );
}
