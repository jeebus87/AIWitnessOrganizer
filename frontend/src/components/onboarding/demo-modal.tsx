"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Users,
  Briefcase,
  FileText,
  Scale,
  Search,
  MessageCircleQuestion,
  Download,
  CreditCard,
  Settings,
  Sparkles,
  ArrowRight,
  ArrowLeft,
  Check,
} from "lucide-react";

interface DemoStep {
  title: string;
  description: string;
  icon: React.ReactNode;
  tips: string[];
}

const demoSteps: DemoStep[] = [
  {
    title: "Welcome to AI Witness Organizer",
    description:
      "Your intelligent partner for extracting and organizing witnesses from legal documents. Let's take a quick tour of the key features.",
    icon: <Sparkles className="h-12 w-12 text-primary" />,
    tips: [
      "AI-powered witness extraction from PDFs, emails, and images",
      "Syncs seamlessly with your Clio matters",
      "Intelligent relevancy analysis and categorization",
    ],
  },
  {
    title: "Matters Dashboard",
    description:
      "Your Clio matters sync automatically on login. View, filter, and select matters for processing.",
    icon: <Briefcase className="h-12 w-12 text-primary" />,
    tips: [
      "Matters sync from Clio automatically",
      "Filter by status, practice area, or client name",
      "Click 'Process' to start witness extraction",
    ],
  },
  {
    title: "Witness Extraction",
    description:
      "Select document folders and start AI-powered extraction. Processing runs in the background while you work.",
    icon: <FileText className="h-12 w-12 text-primary" />,
    tips: [
      "Choose which folders to scan for witnesses",
      "Optionally designate a legal authority folder for context",
      "Track progress on the Jobs page",
    ],
  },
  {
    title: "Witness Directory",
    description:
      "View all extracted witnesses with canonical (deduplicated) and raw views. Filter and search across all your matters.",
    icon: <Users className="h-12 w-12 text-primary" />,
    tips: [
      "Canonical view merges same person across documents",
      "Raw view shows every individual extraction",
      "Filter by role, relevance, or search by name",
    ],
  },
  {
    title: "Relevancy Analysis",
    description:
      "Add allegations and defenses to your matter, then see how each witness relates to specific claims.",
    icon: <Scale className="h-12 w-12 text-primary" />,
    tips: [
      "Add case claims manually or via AI extraction",
      "See which witnesses support or undermine each claim",
      "Track verified vs unverified claims",
    ],
  },
  {
    title: "Legal Research",
    description:
      "Search CourtListener for relevant case law based on your claims and witness observations.",
    icon: <Search className="h-12 w-12 text-primary" />,
    tips: [
      "Integrated CourtListener legal research",
      "Find precedents related to your case",
      "Save selected cases to your Clio matter",
    ],
  },
  {
    title: "Help Assistant",
    description:
      "Click the chat icon in the bottom-right corner anytime for instant help with any feature.",
    icon: <MessageCircleQuestion className="h-12 w-12 text-primary" />,
    tips: [
      "Ask questions about any feature",
      "Get guidance on witness extraction and relevancy",
      "Available on every page",
    ],
  },
  {
    title: "Export Reports",
    description:
      "Download witness reports in multiple formats for trial preparation and discovery.",
    icon: <Download className="h-12 w-12 text-primary" />,
    tips: [
      "Export to PDF for formal witness reports",
      "Export to Excel for data analysis",
      "Export to Word for editing and customization",
    ],
  },
  {
    title: "Credits & Billing",
    description:
      "Free plan includes 10 reports per user per day. Upgrade to Firm Plan for unlimited access.",
    icon: <CreditCard className="h-12 w-12 text-primary" />,
    tips: [
      "Free: 10 reports per user per day",
      "Firm Plan: Unlimited reports for your organization",
      "Admins can purchase bonus credits anytime",
    ],
  },
  {
    title: "Settings & Support",
    description:
      "Manage your firm settings, Clio integration, and billing from the Settings page.",
    icon: <Settings className="h-12 w-12 text-primary" />,
    tips: [
      "Edit firm name (admins only)",
      "Reconnect or resync with Clio",
      "Manage subscription and view usage",
    ],
  },
];

interface DemoModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onComplete?: () => void;
}

export function DemoModal({ open, onOpenChange, onComplete }: DemoModalProps) {
  const [currentStep, setCurrentStep] = useState(0);

  // Reset to first step when modal opens
  useEffect(() => {
    if (open) {
      setCurrentStep(0);
    }
  }, [open]);

  const handleNext = () => {
    if (currentStep < demoSteps.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      // Complete the demo
      localStorage.setItem("aiwitnessfinder_demo_completed", "true");
      onComplete?.();
      onOpenChange(false);
    }
  };

  const handlePrev = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleSkip = () => {
    localStorage.setItem("aiwitnessfinder_demo_completed", "true");
    onComplete?.();
    onOpenChange(false);
  };

  const step = demoSteps[currentStep];
  const isLastStep = currentStep === demoSteps.length - 1;
  const isFirstStep = currentStep === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg" showCloseButton={false}>
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle className="text-xl font-bold">
              Getting Started
            </DialogTitle>
            <div className="flex items-center gap-1">
              {demoSteps.map((_, idx) => (
                <div
                  key={idx}
                  className={`h-1.5 w-4 rounded-full transition-colors ${
                    idx === currentStep
                      ? "bg-primary"
                      : idx < currentStep
                        ? "bg-primary/50"
                        : "bg-muted"
                  }`}
                />
              ))}
            </div>
          </div>
        </DialogHeader>

        <div className="py-6">
          {/* Icon */}
          <div className="flex justify-center mb-6">
            <div className="p-4 rounded-2xl bg-primary/10">{step.icon}</div>
          </div>

          {/* Content */}
          <div className="text-center mb-6">
            <h3 className="text-lg font-semibold mb-2">{step.title}</h3>
            <p className="text-muted-foreground">{step.description}</p>
          </div>

          {/* Tips */}
          <div className="space-y-2">
            {step.tips.map((tip, idx) => (
              <div
                key={idx}
                className="flex items-start gap-3 p-3 rounded-lg bg-muted/50"
              >
                <Check className="h-4 w-4 text-primary mt-0.5 flex-shrink-0" />
                <span className="text-sm">{tip}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between pt-4 border-t">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleSkip}
            className="text-muted-foreground"
          >
            Skip tour
          </Button>

          <div className="flex items-center gap-2">
            {!isFirstStep && (
              <Button variant="outline" size="sm" onClick={handlePrev}>
                <ArrowLeft className="h-4 w-4 mr-1" />
                Back
              </Button>
            )}
            <Button size="sm" onClick={handleNext} className="btn-gradient">
              {isLastStep ? (
                <>
                  Get Started
                  <Check className="h-4 w-4 ml-1" />
                </>
              ) : (
                <>
                  Next
                  <ArrowRight className="h-4 w-4 ml-1" />
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Hook to manage demo state
export function useDemoModal() {
  const [showDemo, setShowDemo] = useState(false);
  const [hasSeenDemo, setHasSeenDemo] = useState(true); // Default true to prevent flash

  useEffect(() => {
    const seen = localStorage.getItem("aiwitnessfinder_demo_completed");
    setHasSeenDemo(seen === "true");

    // Show demo if not seen before
    if (seen !== "true") {
      // Small delay to let the page load first
      const timer = setTimeout(() => {
        setShowDemo(true);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, []);

  const openDemo = () => setShowDemo(true);
  const closeDemo = () => setShowDemo(false);
  const markComplete = () => setHasSeenDemo(true);

  return {
    showDemo,
    setShowDemo,
    hasSeenDemo,
    openDemo,
    closeDemo,
    markComplete,
  };
}
