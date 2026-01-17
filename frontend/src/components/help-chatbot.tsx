"use client";

import { useState, useRef, useEffect } from "react";
import { MessageCircleQuestion, X, Send, Loader2, Bot, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/store/auth";

interface Message {
  role: "user" | "assistant";
  content: string;
}

// Pre-defined help content based on actual app functionality
const HELP_CONTENT = `
AI Witness Organizer Help Guide

## Getting Started
1. Sign in with your Clio account
2. Your matters will sync automatically from Clio
3. Select a matter to process documents and extract witnesses

## Matters
- View all your Clio matters on the Matters page
- Click "Sync Matters" to refresh from Clio
- Use filters to search by status, practice area, or client
- Click a matter to view details and process documents

## Processing Documents
1. Go to a matter's detail page
2. Click "Process Matter" to scan all documents
3. The AI will extract witnesses from PDFs, emails, and images
4. Processing runs in the background - check Jobs for status

## Witnesses
- View all extracted witnesses on the Witnesses page
- Filter by matter, role, or relevance level
- Each witness shows:
  - Name and role (plaintiff, defendant, eyewitness, etc.)
  - Relevance level with legal reasoning
  - Observation (what they witnessed)
  - Contact information (if found)
  - Source document and page number

## Relevance Levels
- **Highly Relevant**: Directly supports or undermines core claims/defenses
- **Relevant**: Has knowledge of facts material to the case
- **Somewhat Relevant**: Peripheral knowledge, may provide context
- **Not Relevant**: Administrative contact only

## Jobs
- Monitor processing jobs on the Jobs page
- See progress, status, and any errors
- Export completed jobs to PDF or Excel

## Exporting Reports
- After processing completes, click "Export PDF" or "Export Excel"
- Reports include all witnesses with their details
- Great for trial preparation and deposition planning

## Subscription & Credits
- Free plan: 10 reports per user per day
- Firm plan: Unlimited reports for $29.99/user/month
- Admins can purchase bonus credits for top-ups
- View credit balance in Settings

## Settings
- View and edit your firm name (admins only)
- Check subscription status and manage billing
- See your credit balance and usage
`;

// Simple keyword-based response system
function getHelpResponse(question: string): string {
  const q = question.toLowerCase();

  if (q.includes("start") || q.includes("begin") || q.includes("how do i")) {
    return "To get started:\n1. Sign in with your Clio account (this happens automatically when you logged in)\n2. Your matters will sync from Clio\n3. Go to the Matters page and select a matter\n4. Click 'Process Matter' to extract witnesses from documents\n\nThe AI will analyze all documents and find potential witnesses automatically.";
  }

  if (q.includes("matter") || q.includes("case")) {
    return "**Matters** are your legal cases synced from Clio.\n\n- View all matters on the Matters page\n- Click 'Sync Matters' to refresh from Clio\n- Use filters to find specific matters\n- Click a matter to view details and process documents";
  }

  if (q.includes("witness")) {
    return "**Witnesses** are automatically extracted from your documents.\n\nEach witness includes:\n- Name and role (plaintiff, defendant, eyewitness, expert, etc.)\n- Relevance level with legal reasoning\n- What they observed or testified\n- Contact information (if found)\n- Source document and page number\n\nView all witnesses on the Witnesses page, or see matter-specific witnesses on a matter's detail page.";
  }

  if (q.includes("process") || q.includes("scan") || q.includes("extract")) {
    return "**Processing Documents:**\n\n1. Go to a matter's detail page\n2. Click 'Process Matter'\n3. The AI scans all documents (PDFs, emails, images)\n4. Witnesses are extracted automatically\n\nProcessing runs in the background - check the Jobs page for status. You'll see:\n- Total documents being processed\n- Progress percentage\n- Witnesses found";
  }

  if (q.includes("relevance") || q.includes("important") || q.includes("level")) {
    return "**Relevance Levels** indicate how important a witness is to your case:\n\n- **Highly Relevant**: Directly supports or undermines core claims/defenses. Critical testimony expected.\n- **Relevant**: Has knowledge of facts material to the case. Likely to be deposed.\n- **Somewhat Relevant**: Peripheral knowledge. May provide context but not central.\n- **Not Relevant**: Administrative contact only. No substantive knowledge.\n\nEach witness also includes a **relevance reason** explaining WHY they're relevant to the specific claims or defenses.";
  }

  if (q.includes("export") || q.includes("pdf") || q.includes("excel") || q.includes("report")) {
    return "**Exporting Reports:**\n\n1. Go to the Jobs page\n2. Find a completed job\n3. Click 'Export PDF' or 'Export Excel'\n\nReports include all extracted witnesses with their:\n- Names and roles\n- Relevance levels and reasons\n- Observations and context\n- Contact information\n- Source documents\n\nGreat for trial preparation and deposition planning!";
  }

  if (q.includes("credit") || q.includes("limit") || q.includes("usage")) {
    return "**Report Credits:**\n\n- **Free plan**: 10 reports per user per day\n- **Firm plan**: Unlimited reports\n\nCredits are used when processing matters. View your balance in Settings.\n\nAdmins can purchase bonus credits:\n- 10 credits: $4.99\n- 25 credits: $12.49\n- 50 credits: $24.99";
  }

  if (q.includes("subscription") || q.includes("billing") || q.includes("upgrade") || q.includes("plan")) {
    return "**Subscription Plans:**\n\n**Free Plan** (default):\n- 10 reports per user per day\n- Basic features\n\n**Firm Plan** ($29.99/user/month):\n- Unlimited reports\n- Priority processing\n- All features\n\nGo to Settings to upgrade or manage billing. Only firm admins can change subscription settings.";
  }

  if (q.includes("job") || q.includes("status") || q.includes("progress")) {
    return "**Jobs Page:**\n\nMonitor your document processing jobs here.\n\n- **Pending**: Waiting to start\n- **Processing**: Currently scanning documents\n- **Completed**: Done! Click to view witnesses or export\n- **Failed**: An error occurred (see error message)\n\nYou can cancel pending jobs or delete completed ones.";
  }

  if (q.includes("setting") || q.includes("account") || q.includes("firm")) {
    return "**Settings Page:**\n\n- **Firm Name**: Your law firm name (admins can edit)\n- **Your Info**: Name and email from Clio\n- **Role**: Admin or Member\n- **Credits**: View remaining daily and bonus credits\n- **Subscription**: View plan status and manage billing\n\nOnly firm admins can change billing settings and purchase credits.";
  }

  if (q.includes("admin")) {
    return "**Admin Permissions:**\n\nThe first user from your Clio firm becomes an admin. Admins can:\n\n- Edit the firm name\n- Manage subscription and billing\n- Purchase bonus credits\n- Access the Stripe billing portal\n\nRegular members can use all features but cannot change billing settings.";
  }

  if (q.includes("clio")) {
    return "**Clio Integration:**\n\nAI Witness Organizer connects to your Clio account to:\n\n- Sync your matters automatically\n- Access documents for analysis\n- Keep everything in sync\n\nYou signed in with Clio OAuth, so your connection is already active. Your Clio data is securely accessed through their official API.";
  }

  // Default response
  return "I can help you with:\n\n- **Getting started** - How to begin using the app\n- **Matters** - Viewing and syncing your cases\n- **Processing** - Scanning documents for witnesses\n- **Witnesses** - Understanding extracted witness data\n- **Relevance levels** - How witnesses are categorized\n- **Exporting** - Creating PDF/Excel reports\n- **Credits** - Usage limits and top-ups\n- **Subscription** - Plans and billing\n- **Settings** - Account and firm settings\n\nAsk me about any of these topics!";
}

export function HelpChatbot() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "Hi! I'm here to help you use AI Witness Organizer. What would you like to know?",
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setIsLoading(true);

    // Simulate a small delay for natural feel
    await new Promise((resolve) => setTimeout(resolve, 500));

    const response = getHelpResponse(userMessage);
    setMessages((prev) => [...prev, { role: "assistant", content: response }]);
    setIsLoading(false);
  };

  return (
    <>
      {/* Chat Button */}
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 h-14 w-14 rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 transition-all flex items-center justify-center z-50"
        aria-label="Open help chat"
      >
        <MessageCircleQuestion className="h-6 w-6" />
      </button>

      {/* Chat Window */}
      {isOpen && (
        <div className="fixed bottom-6 right-6 w-96 h-[500px] bg-background border rounded-lg shadow-xl flex flex-col z-50">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-primary" />
              <span className="font-semibold">Help Assistant</span>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setIsOpen(false)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((message, index) => (
              <div
                key={index}
                className={`flex gap-2 ${
                  message.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {message.role === "assistant" && (
                  <div className="flex-shrink-0 h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                    <Bot className="h-4 w-4 text-primary" />
                  </div>
                )}
                <div
                  className={`max-w-[80%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                    message.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted"
                  }`}
                >
                  {message.content}
                </div>
                {message.role === "user" && (
                  <div className="flex-shrink-0 h-8 w-8 rounded-full bg-primary flex items-center justify-center">
                    <User className="h-4 w-4 text-primary-foreground" />
                  </div>
                )}
              </div>
            ))}
            {isLoading && (
              <div className="flex gap-2 justify-start">
                <div className="flex-shrink-0 h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                  <Bot className="h-4 w-4 text-primary" />
                </div>
                <div className="bg-muted rounded-lg px-3 py-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <form onSubmit={handleSubmit} className="p-4 border-t">
            <div className="flex gap-2">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask a question..."
                disabled={isLoading}
              />
              <Button type="submit" size="icon" disabled={isLoading || !input.trim()}>
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
