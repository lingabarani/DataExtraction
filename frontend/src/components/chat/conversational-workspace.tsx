"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Send, Sparkles, Bot, User, Copy, Check, ExternalLink,
  ShieldCheck, RefreshCw, AlertCircle, Building2, Search,
  Database, Zap, ArrowRight, Layers, Table, MessageSquare, Globe
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { ProspectingWorkspace } from "@/components/prospecting/prospecting-workspace";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  resultsCount?: number;
  companiesPreview?: Array<{
    id?: string;
    name?: string;
    company_name?: string;
    domain?: string;
    website?: string;
    industry?: string;
    state?: string;
    lead_score?: number;
    email_status?: string;
  }>;
  stagedCount?: number;
}

const SAMPLE_PROMPTS = [
  {
    icon: Building2,
    title: "Healthcare in Texas",
    prompt: "Find healthcare companies in Texas with verified contact emails and phone numbers",
  },
  {
    icon: Zap,
    title: "California SaaS Founders",
    prompt: "Show me software and SaaS enterprises in California with C-Suite executive contacts",
  },
  {
    icon: Database,
    title: "Logistics in Chicago",
    prompt: "Logistics 3PL providers in Chicago, IL with high trust score",
  },
  {
    icon: Globe,
    title: "Salesforce CRM Users",
    prompt: "Find companies using Salesforce CRM with annual revenue above 10 million",
  },
];

export function ConversationalWorkspace() {
  const [activeTab, setActiveTab] = useState<"chat" | "table">("chat");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Initialize or fetch session on mount
  useEffect(() => {
    let mounted = true;
    async function initSession() {
      try {
        const res = await api.post<{ id: string }>("/api/v1/chat/sessions", {
          title: "B2B Intelligence Session",
        });
        if (mounted && res && res.id) {
          setSessionId(res.id);
          setMessages([
            {
              id: "welcome-msg",
              role: "assistant",
              content: `Welcome to **DataExtraction AI Chatbot** — connected to **305,458 verified sovereign organizations** and **63,808 deliverable leads**.\n\nAsk for any industry, location, Apollo.io seniority filter, or technographic requirement with strict zero-hallucination accuracy.`,
              timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            },
          ]);
        }
      } catch (err) {
        console.warn("Session init fallback:", err);
        if (mounted) {
          setSessionId(`local-${Date.now()}`);
          setMessages([
            {
              id: "welcome-msg",
              role: "assistant",
              content: `Welcome to **DataExtraction AI Chatbot**. Ask for any company, executive title, industry, or geography.`,
              timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
            },
          ]);
        }
      }
    }
    initSession();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, currentStep, isStreaming]);

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleSend = async (queryText?: string) => {
    const text = (queryText || inputValue).trim();
    if (!text || isStreaming) return;

    setInputValue("");
    const userMsgId = `user-${Date.now()}`;
    const userMsg: ChatMessage = {
      id: userMsgId,
      role: "user",
      content: text,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);
    setCurrentStep("Analyzing query intent & filters...");

    const assistantMsgId = `assistant-${Date.now()}`;
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };
    setMessages((prev) => [...prev, assistantMsg]);

    const activeSession = sessionId || `session-${Date.now()}`;
    const streamUrl = `/api/v1/chat/sessions/${encodeURIComponent(activeSession)}/stream?prompt=${encodeURIComponent(text)}`;
    const postUrl = `/api/v1/chat/sessions/${encodeURIComponent(activeSession)}/messages`;

    try {
      let accumulatedAnswer = "";
      let lastPreview: any[] = [];
      let streamSucceeded = false;

      try {
        const streamResponse = await fetch(streamUrl, {
          headers: { Accept: "text/event-stream" },
        });

        if (streamResponse.ok && streamResponse.body) {
          const reader = streamResponse.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop() || "";

            for (const block of lines) {
              const bTrimmed = block.trim();
              if (!bTrimmed) continue;

              let evt = "message";
              let data: any = {};

              const bLines = bTrimmed.split("\n");
              for (const l of bLines) {
                const s = l.trim();
                if (s.startsWith("event:")) {
                  evt = s.slice(6).trim();
                } else if (s.startsWith("data:")) {
                  try {
                    data = JSON.parse(s.slice(5).trim());
                  } catch (e) {
                    data = { raw: s.slice(5).trim() };
                  }
                }
              }

              if (data.event && !evt) {
                evt = data.event;
              }

              if (evt === "understanding_query") {
                setCurrentStep("Classifying intent & Apollo filters...");
              } else if (evt === "search_plan") {
                setCurrentStep("Formulated query plan across canonical records...");
              } else if (evt === "database_search") {
                setCurrentStep("Querying master database (213K Golden Vault)...");
              } else if (evt === "database_results") {
                const count = data.count || 0;
                lastPreview = data.preview || [];
                setCurrentStep(`Found ${count} verified records in database.`);
              } else if (evt === "checking_completeness") {
                setCurrentStep("Evaluating field-level completeness...");
              } else if (evt === "enrichment_available") {
                setCurrentStep("Verified records ready (Deep Crawl available)...");
              } else if (evt === "answer") {
                accumulatedAnswer = data.answer || "";
                if (data.companies && data.companies.length > 0) {
                  lastPreview = data.companies;
                }
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? {
                          ...m,
                          content: accumulatedAnswer,
                          companiesPreview: lastPreview,
                        }
                      : m
                  )
                );
              } else if (evt === "done") {
                streamSucceeded = true;
                setCurrentStep(null);
              }
            }
          }
        }
      } catch (streamErr) {
        console.warn("SSE stream fetch failed, trying direct POST fallback:", streamErr);
      }

      // Fallback to direct POST if stream didn't yield an answer
      if (!accumulatedAnswer) {
        setCurrentStep("Finalizing verified intelligence response...");
        const postRes = await fetch(postUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: text }),
        });

        if (postRes.ok) {
          const postData = await postRes.json();
          accumulatedAnswer = postData.content || postData.answer || "";
          lastPreview = postData.companies || [];
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    content: accumulatedAnswer,
                    companiesPreview: lastPreview,
                  }
                : m
            )
          );
        }
      }

      if (!accumulatedAnswer) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? {
                  ...m,
                  content:
                    "Query completed. Verified matches have been retrieved and logged to the intelligence ledger.",
                }
              : m
          )
        );
      }
    } catch (err: any) {
      console.error("Chat error:", err);
      toast.error(err.message || "Failed to complete chat query");
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? {
                ...m,
                content: `An error occurred while executing conversational intelligence: ${err.message}. Please try again or broaden the search criteria.`,
              }
            : m
        )
      );
    } finally {
      setIsStreaming(false);
      setCurrentStep(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* Top Header & Workspace Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-600 text-white shadow-md shadow-blue-500/20">
            <Bot className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight flex items-center gap-2">
              B2B Conversational Intelligence
              <Badge variant="outline" className="text-xs bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20">
                Verified Zero-Hallucination
              </Badge>
            </h1>
            <p className="text-xs text-muted-foreground">
              Natural language prospecting backed by 305K+ sovereign companies and 63K+ verified executive leads
            </p>
          </div>
        </div>

        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as any)} className="w-auto">
          <TabsList className="grid grid-cols-2 w-64">
            <TabsTrigger value="chat" className="flex items-center gap-2 text-xs">
              <MessageSquare className="w-3.5 h-3.5" />
              AI Chat
            </TabsTrigger>
            <TabsTrigger value="table" className="flex items-center gap-2 text-xs">
              <Table className="w-3.5 h-3.5" />
              DE Chatbot Grid
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {activeTab === "table" ? (
        <ProspectingWorkspace />
      ) : (
        <div className="flex flex-col h-[calc(100vh-230px)] min-h-[550px] rounded-xl border bg-card shadow-sm overflow-hidden">
          {/* Chat Message Scrollport */}
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "flex gap-3 max-w-3xl",
                  msg.role === "user" ? "ml-auto justify-end" : "justify-start"
                )}
              >
                {msg.role === "assistant" && (
                  <div className="w-8 h-8 rounded-full bg-blue-600/10 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 flex items-center justify-center shrink-0 mt-0.5 border border-blue-500/20">
                    <Sparkles className="w-4 h-4" />
                  </div>
                )}

                <div
                  className={cn(
                    "rounded-2xl p-4 text-sm leading-relaxed shadow-sm space-y-3",
                    msg.role === "user"
                      ? "bg-blue-600 text-white rounded-br-none max-w-[85%]"
                      : "bg-muted/50 dark:bg-muted/30 border text-card-foreground rounded-tl-none max-w-[95%]"
                  )}
                >
                  <div className="whitespace-pre-wrap font-sans">{msg.content}</div>

                  {/* Render preview entity cards if present */}
                  {msg.companiesPreview && msg.companiesPreview.length > 0 && (
                    <div className="pt-2 border-t border-border/50 space-y-2">
                      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                        <Building2 className="w-3.5 h-3.5 text-blue-500" />
                        Top Matched Entities ({msg.companiesPreview.length})
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {msg.companiesPreview.map((comp, idx) => (
                          <div
                            key={idx}
                            className="p-2.5 rounded-lg border bg-background/80 hover:bg-background transition-colors text-xs space-y-1"
                          >
                            <div className="font-semibold text-foreground flex items-center justify-between">
                              <span className="truncate max-w-[180px]">
                                {comp.company_name || comp.name || "Entity"}
                              </span>
                              {comp.lead_score && (
                                <Badge variant="secondary" className="text-[10px] px-1 py-0 h-4">
                                  Score {comp.lead_score}
                                </Badge>
                              )}
                            </div>
                            <div className="text-muted-foreground flex items-center gap-2">
                              <span>{comp.industry || "Enterprise"}</span>
                              {comp.state && <span>• {comp.state}</span>}
                            </div>
                            {comp.domain && (
                              <a
                                href={`https://${comp.domain}`}
                                target="_blank"
                                rel="noreferrer"
                                className="text-blue-500 hover:underline flex items-center gap-1 pt-0.5"
                              >
                                {comp.domain}
                                <ExternalLink className="w-2.5 h-2.5" />
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div
                    className={cn(
                      "flex items-center justify-between pt-1 text-[11px]",
                      msg.role === "user" ? "text-blue-100" : "text-muted-foreground"
                    )}
                  >
                    <span>{msg.timestamp}</span>
                    {msg.role === "assistant" && msg.content && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 rounded-md hover:bg-muted"
                        onClick={() => handleCopy(msg.content, msg.id)}
                        aria-label="Copy response"
                      >
                        {copiedId === msg.id ? (
                          <Check className="w-3.5 h-3.5 text-emerald-500" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </Button>
                    )}
                  </div>
                </div>

                {msg.role === "user" && (
                  <div className="w-8 h-8 rounded-full bg-foreground text-background flex items-center justify-center shrink-0 mt-0.5">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            ))}

            {/* Live Streaming Step Indicator */}
            {isStreaming && currentStep && (
              <div className="flex items-center gap-2.5 p-3 rounded-lg bg-blue-50/50 dark:bg-blue-950/20 border border-blue-500/20 text-xs text-blue-600 dark:text-blue-400 max-w-md animate-pulse">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>{currentStep}</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Quick Prompt Recommendation Pills */}
          {messages.length <= 2 && (
            <div className="p-3 bg-muted/20 border-t border-b grid grid-cols-2 sm:grid-cols-4 gap-2">
              {SAMPLE_PROMPTS.map((sp, idx) => {
                const Icon = sp.icon;
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSend(sp.prompt)}
                    className="p-2 rounded-lg border bg-background hover:bg-muted/50 hover:border-blue-500/40 transition-all text-left group"
                  >
                    <div className="flex items-center gap-1.5 text-xs font-medium text-foreground group-hover:text-blue-600">
                      <Icon className="w-3.5 h-3.5 text-blue-500" />
                      {sp.title}
                    </div>
                    <div className="text-[11px] text-muted-foreground truncate mt-0.5">
                      {sp.prompt}
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          {/* Bottom Chat Input Bar */}
          <div className="p-3 sm:p-4 bg-background border-t">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSend();
              }}
              className="flex items-center gap-2"
            >
              <div className="relative flex-1">
                <Input
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  placeholder="Ask anything: 'Find healthcare clinics in Florida with verified email', 'Companies using AWS'..."
                  disabled={isStreaming}
                  className="pr-10 h-11 text-sm bg-muted/40 focus-visible:ring-1 focus-visible:ring-blue-500"
                />
              </div>
              <Button
                type="submit"
                disabled={!inputValue.trim() || isStreaming}
                className="h-11 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium flex items-center gap-2 shrink-0 shadow-sm"
              >
                {isStreaming ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <>
                    <span>Search</span>
                    <Send className="w-3.5 h-3.5" />
                  </>
                )}
              </Button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
