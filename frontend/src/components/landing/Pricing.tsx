"use client";

import { Button } from "@/components/ui/button";
import { Check } from "lucide-react";
import { useAuthStore } from "@/store/auth";

const tiers = [
    {
        name: "Free",
        price: "$0",
        description: "Get started with AI-powered witness extraction.",
        features: [
            "10 reports per user per day",
            "AI witness extraction",
            "Clio integration",
            "PDF & Excel exports",
            "Email support",
        ],
        cta: "Get Started Free",
    },
    {
        name: "Firm Plan",
        price: "$29.99",
        priceDetail: "/user/month",
        description: "Unlimited processing for your entire firm.",
        features: [
            "14-day free trial",
            "Unlimited reports",
            "Unlimited matters",
            "Priority processing",
            "Bulk export",
            "Priority support",
        ],
        featured: true,
        cta: "Start Free Trial",
    },
];

const topUpPackages = [
    { credits: 10, price: "$4.99" },
    { credits: 25, price: "$12.49" },
    { credits: 50, price: "$24.99" },
];

export function Pricing() {
    const { login } = useAuthStore();

    const handleGetStarted = () => {
        login();
    };

    return (
        <section id="pricing" className="py-24">
            <div className="container mx-auto px-4">
                <div className="text-center max-w-3xl mx-auto mb-16">
                    <h2 className="text-3xl font-bold tracking-tight mb-4">
                        Simple, Transparent Pricing
                    </h2>
                    <p className="text-lg text-muted-foreground">
                        Start free, upgrade when you need more. No hidden fees. Cancel anytime.
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl mx-auto mb-16">
                    {tiers.map((tier) => (
                        <div
                            key={tier.name}
                            className={`relative p-8 rounded-3xl border flex flex-col ${tier.featured
                                ? "bg-muted/30 border-primary/50 shadow-xl"
                                : "bg-card shadow-sm hover:shadow-md transition-shadow"
                                }`}
                        >
                            {tier.featured && (
                                <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 bg-primary text-primary-foreground text-sm font-medium rounded-full">
                                    14-Day Free Trial
                                </div>
                            )}

                            <div className="mb-8">
                                <h3 className="text-xl font-bold mb-2">{tier.name}</h3>
                                <div className="flex items-baseline gap-1 mb-4">
                                    <span className="text-4xl font-bold">{tier.price}</span>
                                    <span className="text-muted-foreground">
                                        {tier.priceDetail || (tier.price === "$0" ? "" : "/month")}
                                    </span>
                                </div>
                                <p className="text-muted-foreground text-sm">
                                    {tier.description}
                                </p>
                            </div>

                            <div className="flex-1 space-y-4 mb-8">
                                {tier.features.map((feature) => (
                                    <div key={feature} className="flex items-center gap-3">
                                        <div className="flex-shrink-0 w-5 h-5 rounded-full bg-green-500/10 flex items-center justify-center">
                                            <Check className="h-3 w-3 text-green-600" />
                                        </div>
                                        <span className="text-sm">{feature}</span>
                                    </div>
                                ))}
                            </div>

                            <Button
                                variant={tier.featured ? "default" : "outline"}
                                className="w-full rounded-full"
                                onClick={handleGetStarted}
                            >
                                {tier.cta}
                            </Button>
                        </div>
                    ))}
                </div>

                {/* Credit Top-Ups */}
                <div className="max-w-2xl mx-auto text-center">
                    <h3 className="text-lg font-semibold mb-4">Need More Credits?</h3>
                    <p className="text-sm text-muted-foreground mb-6">
                        Free plan users can purchase additional report credits anytime.
                    </p>
                    <div className="flex justify-center gap-4 flex-wrap">
                        {topUpPackages.map((pkg) => (
                            <div
                                key={pkg.credits}
                                className="px-6 py-3 rounded-xl border bg-card text-sm"
                            >
                                <span className="font-semibold">{pkg.credits} credits</span>
                                <span className="text-muted-foreground"> for </span>
                                <span className="font-semibold text-primary">{pkg.price}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </section>
    );
}
