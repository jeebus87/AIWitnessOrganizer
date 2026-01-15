"use client";

import { Button } from "@/components/ui/button";
import { Check } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { api } from "@/lib/api";

const tiers = [
    {
        name: "Basic",
        id: "price_1SpkLcBS2VKrUF7Ru3SNu2Wp",
        price: "$49",
        description: "Essential tools for solo practitioners.",
        features: [
            "5 Matters per month",
            "Basic AI Extraction",
            "Clio Integration",
            "Email Support",
        ],
    },
    {
        name: "Professional",
        id: "price_1SpkLsBS2VKrUF7RJJty99ye",
        price: "$149",
        description: "Perfect for growing law firms.",
        features: [
            "Unlimited Matters",
            "Advanced AI Context",
            "Priority Processing",
            "Priority Support",
            "Bulk Export",
        ],
        featured: true,
    },
    {
        name: "Enterprise",
        id: "price_1SpkLuBS2VKrUF7Rz2AAxSgu",
        price: "$499",
        description: "For large firms with high volume.",
        features: [
            "Unlimited Everything",
            "Custom AI Models",
            "Dedicated Account Manager",
            "SLA Guarantees",
            "API Access",
        ],
    },
];

export function Pricing() {
    const { userProfile, token, login } = useAuthStore();

    const handleSubscribe = async (priceId: string) => {
        if (!token) {
            login();
            return;
        }

        // If already subscribed, redirect to portal, else checkout
        if (userProfile?.subscription_tier !== 'free') {
            const { url } = await api.createPortalSession(token);
            // eslint-disable-next-line
            window.location.href = url;
            return;
        }

        const { url } = await api.createCheckoutSession(token, priceId);
        // eslint-disable-next-line
        window.location.href = url;
    };

    return (
        <section id="pricing" className="py-24">
            <div className="container mx-auto px-4">
                <div className="text-center max-w-3xl mx-auto mb-16">
                    <h2 className="text-3xl font-bold tracking-tight mb-4">
                        Simple, Transparent Pricing
                    </h2>
                    <p className="text-lg text-muted-foreground">
                        Choose the plan that fits your firm size. No hidden fees. Cancel anytime.
                    </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-6xl mx-auto">
                    {tiers.map((tier) => (
                        <div
                            key={tier.name}
                            className={`relative p-8 rounded-3xl border flex flex-col ${tier.featured
                                ? "bg-muted/30 border-blue-500/50 shadow-xl scale-105 z-10"
                                : "bg-card shadow-sm hover:shadow-md transition-shadow"
                                }`}
                        >
                            {tier.featured && (
                                <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 bg-blue-600 text-white text-sm font-medium rounded-full">
                                    Most Popular
                                </div>
                            )}

                            <div className="mb-8">
                                <h3 className="text-xl font-bold mb-2">{tier.name}</h3>
                                <div className="flex items-baseline gap-1 mb-4">
                                    <span className="text-4xl font-bold">{tier.price}</span>
                                    <span className="text-muted-foreground">/month</span>
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
                                className={`w-full rounded-full ${tier.featured ? "bg-blue-600 hover:bg-blue-700" : ""
                                    }`}
                                onClick={() => handleSubscribe(tier.id)}
                            >
                                {userProfile?.subscription_tier === 'free' || !userProfile
                                    ? "Get Started"
                                    : "Upgrade"}
                            </Button>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
