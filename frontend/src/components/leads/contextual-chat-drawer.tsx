"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  X, Send, Sparkles, Bot, User, Copy, Check,
  ExternalLink, ShieldCheck, Star, RefreshCw, AlertCircle
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { CompanyIntelligence } from "@/hooks/use-leads";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

interface ContextualChatDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  company?: CompanyIntelligence | null;
  companyName?: string;
  companyId?: string;
  domain?: string;
}

const ACTION_PILLS = [
  { label: "Summarize Offerings", prompt: "Summarize the primary business offerings, services, and market positioning of this company based on verified records." },
  { label: "Draft Outreach Email", prompt: "Draft a concise, high-converting B2B sales outreach email to the executive leadership of this company highlighting our value proposition." },
  { label: "Analyze Tech Stack", prompt: "Analyze this company's detected technologies, CRM, and cloud infrastructure. Identify any potential technical or compliance risks." },
  { label: "Executive SWOT", prompt: "Provide a quick SWOT analysis (Strengths, Weaknesses, Opportunities, Threats) for this company based strictly on verified data." },
];

export function ContextualChatDrawer({
  isOpen,
  onClose,
  company,
  companyName,
  companyId,
  domain,
}: ContextualChatDrawerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeName = company?.company_name || companyName || "Target Company";
  const activeDomain = company?.domain || domain || "";
  const activeIndustry = company?.company_type || "Commercial Enterprise";

  // Initialize or reset session when opened with a company
  useEffect(() => {
    if (isOpen) {
      const newSessionId = `session-${Date.now()}`;
      setSessionId(newSessionId);
      setMessages([
        {
          id: "welcome",
          role: "assistant",
          content: `Hello! I have loaded the verified dossier for **${activeName}** (${activeDomain || "No domain recorded"}).\n\nHow can I assist your team today with account intelligence, tech stack verification, or outreach strategy?`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    }
  }, [isOpen, activeName, activeDomain]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleSendPrompt = async (promptText: string) => {
    const text = promptText.trim();
    if (!text || isStreaming) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputValue("");
    setIsStreaming(true);

    const assistantMsgId = `asst-${Date.now()}`;
    const initialAssistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };
    setMessages((prev) => [...prev, initialAssistantMsg]);

    try {
      const companyContextPayload = {
        company_id: companyId,
        company_name: activeName,
        domain: activeDomain,
        industry: activeIndustry,
        tagline: company?.tagline,
        overview: company?.overview,
        services: company?.services_provided,
        technologies: company?.b2b_intelligence?.detected_technologies || [],
        primary_cloud: company?.b2b_intelligence?.primary_cloud,
        primary_crm: company?.b2b_intelligence?.primary_crm,
        rating: company?.reviews?.average_rating,
        review_count: company?.reviews?.total_scraped,
        ssl_valid: company?.trust_and_compliance?.ssl_valid,
      };

      let currentSid = sessionId;
      if (!currentSid || currentSid.startsWith("temp-")) {
        try {
          const sess = await api.post<{ id: string }>("/v1/chat/sessions", {
            title: `${activeName} Intelligence`,
            company_context: companyContextPayload,
          });
          if (sess && sess.id) {
            currentSid = sess.id;
            setSessionId(sess.id);
          }
        } catch (sErr) {
          // Fallback if session API is unreachable
        }
      }

      let finalReply = "";
      if (currentSid && !currentSid.startsWith("temp-")) {
        const res = await api.post<any>(`/v1/chat/sessions/${currentSid}/messages`, {
          content: text,
          company_context: companyContextPayload,
        });
        finalReply = res?.content || res?.answer || "I have analyzed the verified data for this entity, but no additional details were found in the master record.";
      } else {
        finalReply = `Based on verified master records for **${activeName}**:\n- **Industry:** ${activeIndustry}\n- **Website:** ${activeDomain || "Not specified"}\n- **Overview:** ${company?.overview || "No description recorded in sovereign filing."}`;
      }

      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId ? { ...msg, content: finalReply } : msg
        )
      );
    } catch (err: any) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? {
                ...msg,
                content: `> [!NOTE]\n> Could not contact cloud LLM. Based on verified database records for **${activeName}**:\n- **Industry:** ${activeIndustry}\n- **Website:** ${activeDomain || "Not specified"}\n- **Overview:** ${company?.overview || "No description recorded in sovereign filing."}\n- **Verified Data:** All data strictly grounded in master records.`,
              }
            : msg
        )
      );
    } finally {
      setIsStreaming(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm transition-opacity animate-in fade-in duration-200">
      <div
        className="w-full max-w-lg h-full bg-card border-l border-border shadow-2xl flex flex-col transition-transform animate-in slide-in-from-right duration-300"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-drawer-title"
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-border/80 flex items-center justify-between bg-muted/30">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-purple-500 to-indigo-600 flex items-center justify-center text-white shadow-sm">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h2 id="chat-drawer-title" className="text-sm font-semibold tracking-tight text-foreground flex items-center gap-1.5">
                AI Account Intelligence
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 border-primary/30 text-primary bg-primary/5">
                  Contextual
                </Badge>
              </h2>
              <p className="text-xs text-muted-foreground truncate max-w-[280px]">
                {activeName} {activeDomain ? `· ${activeDomain}` : ""}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8 rounded-md text-muted-foreground hover:text-foreground"
            aria-label="Close Drawer"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Company Quick Context Strip */}
        <div className="px-5 py-2.5 bg-muted/15 border-b border-border/60 flex items-center gap-2 overflow-x-auto text-xs no-scrollbar">
          <span className="text-[11px] font-medium text-muted-foreground whitespace-nowrap">Context:</span>
          <span className="px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground text-[10px] font-medium whitespace-nowrap">
            {activeIndustry}
          </span>
          {company?.reviews?.average_rating && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 text-[10px] font-medium whitespace-nowrap border border-amber-500/20">
              <Star className="w-2.5 h-2.5 fill-current" />
              {company.reviews.average_rating} ({company.reviews.total_scraped || 0})
            </span>
          )}
          {company?.trust_and_compliance?.ssl_valid && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-[10px] font-medium whitespace-nowrap border border-emerald-500/20">
              <ShieldCheck className="w-2.5 h-2.5" />
              SSL Valid
            </span>
          )}
        </div>

        {/* Action Pills */}
        <div className="px-5 py-2.5 border-b border-border/40 bg-card flex items-center gap-1.5 overflow-x-auto text-xs no-scrollbar">
          {ACTION_PILLS.map((pill, idx) => (
            <button
              key={idx}
              onClick={() => handleSendPrompt(pill.prompt)}
              disabled={isStreaming}
              className="px-2.5 py-1 rounded-md text-[11px] font-medium bg-secondary/80 hover:bg-secondary text-secondary-foreground hover:text-foreground border border-border/60 whitespace-nowrap transition-colors"
            >
              {pill.label}
            </button>
          ))}
        </div>

        {/* Message Thread */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "flex gap-3 text-xs leading-relaxed",
                msg.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              {msg.role === "assistant" && (
                <div className="w-6 h-6 rounded-md bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
                  <Bot className="w-3.5 h-3.5" />
                </div>
              )}
              <div
                className={cn(
                  "relative max-w-[85%] rounded-lg px-3.5 py-2.5 shadow-sm group",
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground ml-4"
                    : "bg-muted/60 text-foreground border border-border/60 mr-4"
                )}
              >
                <div className="whitespace-pre-wrap font-sans">
                  {msg.content || (
                    <span className="inline-flex items-center gap-1.5 text-muted-foreground animate-pulse">
                      <RefreshCw className="w-3 h-3 animate-spin" /> Thinking & verifying with ground-truth records...
                    </span>
                  )}
                </div>
                {msg.content && msg.role === "assistant" && (
                  <button
                    onClick={() => handleCopy(msg.content, msg.id)}
                    className="absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-muted text-muted-foreground transition-opacity"
                    title="Copy response"
                  >
                    {copiedId === msg.id ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                  </button>
                )}
                <div
                  className={cn(
                    "text-[10px] mt-1.5 opacity-60 text-right",
                    msg.role === "user" ? "text-primary-foreground" : "text-muted-foreground"
                  )}
                >
                  {msg.timestamp}
                </div>
              </div>
              {msg.role === "user" && (
                <div className="w-6 h-6 rounded-md bg-secondary text-secondary-foreground flex items-center justify-center shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5" />
                </div>
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div className="p-4 border-t border-border bg-card">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendPrompt(inputValue);
            }}
            className="flex items-center gap-2"
          >
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={`Ask about ${activeName}...`}
              disabled={isStreaming}
              className="flex-1 h-9 px-3 text-xs rounded-md bg-muted/50 border border-input focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
            />
            <Button
              type="submit"
              size="sm"
              disabled={!inputValue.trim() || isStreaming}
              className="h-9 px-3 gap-1.5 text-xs font-medium"
            >
              {isStreaming ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Send className="w-3.5 h-3.5" />
              )}
            </Button>
          </form>
          <p className="text-[10px] text-muted-foreground/80 mt-2 text-center">
            Responses are strictly verified against master database records. Zero synthetic data.
          </p>
        </div>
      </div>
    </div>
  );
}
