"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  Download,
  ExternalLink,
  Globe,
  Loader2,
  Mail,
  MapPin,
  MessageSquare,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  StopCircle,
  Trash2,
  User,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  chatApi,
  ChatCompany,
  ChatMessage,
  ChatSession,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

const SUGGESTED_QUERIES = [
  "Find healthcare companies in Texas with emails and phone numbers",
  "Find manufacturing companies in California with verified emails",
  "Find Dallas companies with CEO and contact details",
  "Find software companies in New York with contact emails",
];

export default function ChatbotPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputPrompt, setInputPrompt] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamSteps, setStreamSteps] = useState<Array<{ event: string; title: string; data: any; status: "active" | "done" }>>([]);
  const [activeCompanies, setActiveCompanies] = useState<ChatCompany[]>([]);
  const [showSteps, setShowSteps] = useState(true);

  const eventSourceRef = useRef<EventSource | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  // Scroll to bottom when messages or stream steps update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamSteps]);

  const loadSessions = async () => {
    try {
      const list = await chatApi.listSessions(30);
      setSessions(list);
      if (list.length > 0 && !activeSessionId) {
        selectSession(list[0].id);
      } else if (list.length === 0) {
        handleNewSession();
      }
    } catch (err: any) {
      console.error("Failed to load sessions:", err);
    }
  };

  const selectSession = async (id: string) => {
    eventSourceRef.current?.close();
    setIsStreaming(false);
    setStreamSteps([]);
    setActiveSessionId(id);
    try {
      const history = await chatApi.getHistory(id);
      setMessages(history);
      // Pick last companies if present
      const lastAsst = [...history].reverse().find((m) => m.role === "assistant" && m.companies);
      if (lastAsst?.companies) {
        setActiveCompanies(lastAsst.companies);
      } else {
        setActiveCompanies([]);
      }
    } catch (err: any) {
      toast.error("Failed to load conversation history");
    }
  };

  const handleNewSession = async () => {
    try {
      const newSess = await chatApi.createSession("New Conversation");
      setSessions((prev) => [newSess, ...prev]);
      setActiveSessionId(newSess.id);
      setMessages([]);
      setActiveCompanies([]);
      setStreamSteps([]);
    } catch (err: any) {
      toast.error("Could not create new session");
    }
  };

  const handleDeleteSession = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await chatApi.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        const remaining = sessions.filter((s) => s.id !== id);
        if (remaining.length > 0) {
          selectSession(remaining[0].id);
        } else {
          handleNewSession();
        }
      }
      toast.success("Session deleted");
    } catch (err: any) {
      toast.error("Failed to delete session");
    }
  };

  const handleStop = async () => {
    if (activeSessionId) {
      try {
        await chatApi.cancelExecution(activeSessionId);
      } catch (err) {}
    }
    eventSourceRef.current?.close();
    setIsStreaming(false);
    toast.info("Search generation stopped");
  };

  const handleSendMessage = async (textToSend?: string) => {
    const text = (textToSend ?? inputPrompt).trim();
    if (!text || isStreaming || !activeSessionId) return;

    setInputPrompt("");
    setStreamSteps([]);
    setIsStreaming(true);

    // Optimistically append user message
    const tempUserMsg: ChatMessage = {
      id: "temp-" + Date.now(),
      session_id: activeSessionId,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    // Build SSE Stream URL with auth token
    const streamUrl = chatApi.getStreamUrl(activeSessionId, text);
    const es = new EventSource(streamUrl);
    eventSourceRef.current = es;

    const stepLabels: Record<string, string> = {
      understanding_query: "Natural-Language Intent Understanding",
      search_plan: "Validated Search Plan",
      database_search: "Searching PostgreSQL Database",
      database_results: "Database Records Retrieved",
      checking_completeness: "Field-Level Completeness Analysis",
      live_discovery_started: "Live Discovery Fallback Triggered",
      discovery_progress: "Federated Source Discovery Progress",
      discovery_results: "Live Discovery Results Merged",
      merging_results: "Entity Reconciliation & Provenance",
      saving_for_review: "Staging Discoveries in Review Queue",
    };

    es.addEventListener("open", () => {
      // Stream connection opened
    });

    // Listen to custom SSE events
    const eventTypes = [
      "message_received",
      "understanding_query",
      "search_plan",
      "database_search",
      "database_results",
      "checking_completeness",
      "completeness_report",
      "live_discovery_started",
      "discovery_progress",
      "discovery_results",
      "merging_results",
      "saving_for_review",
      "answer",
      "done",
      "error",
    ];

    eventTypes.forEach((evtName) => {
      es.addEventListener(evtName, (e: MessageEvent) => {
        try {
          const payload = JSON.parse(e.data);

          if (evtName === "answer") {
            const assistantMsg: ChatMessage = {
              id: payload.message_id || "asst-" + Date.now(),
              session_id: activeSessionId,
              role: "assistant",
              content: payload.content || "",
              companies: payload.companies || [],
              created_at: new Date().toISOString(),
            };
            setMessages((prev) => [...prev, assistantMsg]);
            if (payload.companies) {
              setActiveCompanies(payload.companies);
            }
          } else if (evtName === "done") {
            setIsStreaming(false);
            es.close();
            // Refresh sessions to get updated title
            chatApi.listSessions().then(setSessions);
          } else if (evtName === "error") {
            toast.error(payload.error || "An error occurred during search");
            setIsStreaming(false);
            es.close();
          } else if (stepLabels[evtName]) {
            setStreamSteps((prev) => {
              const existingIdx = prev.findIndex((s) => s.event === evtName);
              const newStep = {
                event: evtName,
                title: stepLabels[evtName],
                data: payload,
                status: "done" as const,
              };
              if (existingIdx >= 0) {
                const copy = [...prev];
                copy[existingIdx] = newStep;
                return copy;
              }
              return [...prev, newStep];
            });
          }
        } catch (parseErr) {
          console.error("SSE parse error:", parseErr);
        }
      });
    });

    es.onerror = () => {
      setIsStreaming(false);
      es.close();
    };
  };

  const handleExportCSV = () => {
    if (activeCompanies.length === 0) {
      toast.info("No company records to export");
      return;
    }
    const headers = ["Company Name", "Industry", "Website", "Phone", "Email", "Location", "Leadership", "Origin", "Status"];
    const rows = activeCompanies.map((c) => [
      `"${c.company_name || ""}"`,
      `"${c.industry || ""}"`,
      `"${c.website || c.domain || ""}"`,
      `"${c.phone || ""}"`,
      `"${c.email || ""}"`,
      `"${c.address_city || ""}, ${c.address_state || ""}"`,
      `"${c.executive || ""}"`,
      `"${c.origin || "Database"}"`,
      `"${c.pending_review ? "Pending Review" : "Verified"}"`,
    ]);
    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `b2b_chat_export_${Date.now()}.csv`;
    link.click();
    toast.success("Exported records to CSV");
  };

  return (
    <div className="flex h-[calc(100vh-4rem)] overflow-hidden bg-background">
      {/* ── Left Sidebar: Conversation Sessions ─────────────────────────────── */}
      <div className="w-72 border-r bg-muted/20 flex flex-col justify-between">
        <div className="p-3 border-b flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            <span className="font-semibold text-sm">AI Chat Sessions</span>
          </div>
          <Button size="sm" variant="outline" className="h-8 gap-1" onClick={handleNewSession}>
            <Plus className="w-3.5 h-3.5" />
            New
          </Button>
        </div>

        {/* Sessions list */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.map((s) => (
            <div
              key={s.id}
              onClick={() => selectSession(s.id)}
              className={`group flex items-center justify-between px-3 py-2 rounded-md text-xs cursor-pointer transition-colors ${
                activeSessionId === s.id
                  ? "bg-primary text-primary-foreground font-medium"
                  : "hover:bg-muted text-muted-foreground"
              }`}
            >
              <div className="flex items-center gap-2 truncate">
                <MessageSquare className="w-3.5 h-3.5 flex-shrink-0" />
                <span className="truncate">{s.title || "Conversation"}</span>
              </div>
              <button
                onClick={(e) => handleDeleteSession(s.id, e)}
                className={`opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 transition-opacity ${
                  activeSessionId === s.id ? "text-primary-foreground" : "text-muted-foreground"
                }`}
                title="Delete conversation"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
          {sessions.length === 0 && (
            <div className="text-center py-8 text-xs text-muted-foreground">
              No conversations yet. Start a new chat!
            </div>
          )}
        </div>

        {/* Review Queue Shortcut in Sidebar */}
        <div className="p-3 border-t bg-muted/40">
          <Link href="/reviews">
            <Button variant="outline" size="sm" className="w-full justify-start gap-2 h-9 text-xs">
              <ShieldCheck className="w-4 h-4 text-emerald-500" />
              <span>Review Staged Queue</span>
            </Button>
          </Link>
        </div>
      </div>

      {/* ── Main Chat Area ──────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header Bar */}
        <div className="h-12 border-b px-4 flex items-center justify-between bg-card">
          <div className="flex items-center gap-2">
            <Bot className="w-5 h-5 text-primary" />
            <span className="font-medium text-sm">B2B Intelligence Assistant</span>
            <Badge variant="secondary" className="text-2xs uppercase tracking-wider">
              Local LLaMA 3.1 + Live Discovery
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            {activeCompanies.length > 0 && (
              <Button size="sm" variant="outline" className="h-8 gap-1.5 text-xs" onClick={handleExportCSV}>
                <Download className="w-3.5 h-3.5" />
                Export ({activeCompanies.length})
              </Button>
            )}
            <Link href="/reviews">
              <Button size="sm" variant="ghost" className="h-8 gap-1.5 text-xs text-amber-500 hover:text-amber-600">
                <ShieldAlert className="w-3.5 h-3.5" />
                Review Staging
              </Button>
            </Link>
          </div>
        </div>

        {/* Messages Stream */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="max-w-2xl mx-auto py-12 text-center space-y-6">
              <div className="inline-flex p-3 rounded-full bg-primary/10 text-primary">
                <Sparkles className="w-8 h-8" />
              </div>
              <div>
                <h3 className="text-lg font-semibold">How can I assist your B2B search today?</h3>
                <p className="text-xs text-muted-foreground mt-1">
                  Ask natural-language queries. I search existing database records first, analyze field completeness,
                  and automatically enrich missing information using Live Discovery.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-left">
                {SUGGESTED_QUERIES.map((q, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleSendMessage(q)}
                    className="p-3 text-xs rounded-lg border bg-card hover:bg-muted/60 transition-colors text-foreground text-left"
                  >
                    "{q}"
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={msg.id || i}
              className={`flex gap-3 max-w-4xl mx-auto ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              {msg.role === "assistant" && (
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 text-primary mt-1">
                  <Bot className="w-4 h-4" />
                </div>
              )}

              <div
                className={`rounded-lg px-4 py-3 max-w-[85%] text-xs leading-relaxed space-y-2 ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground font-medium"
                    : "bg-card border shadow-sm text-card-foreground"
                }`}
              >
                <div className="whitespace-pre-wrap">{msg.content}</div>

                {/* Render Result Cards if attached to assistant message */}
                {msg.companies && msg.companies.length > 0 && (
                  <div className="pt-2 space-y-2">
                    <Separator className="my-2" />
                    <div className="font-semibold text-xs flex items-center justify-between">
                      <span>Matching Companies ({msg.companies.length})</span>
                      <Button size="sm" variant="ghost" className="h-6 text-2xs" onClick={handleExportCSV}>
                        <Download className="w-3 h-3 mr-1" /> Export CSV
                      </Button>
                    </div>

                    <div className="grid grid-cols-1 gap-2 pt-1">
                      {msg.companies.slice(0, 8).map((comp, cIdx) => (
                        <div
                          key={comp.company_id || cIdx}
                          className="p-3 rounded-md border bg-background/50 hover:bg-muted/40 transition-colors space-y-1.5"
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-sm text-foreground">
                              {comp.company_name || comp.canonical_name}
                            </span>
                            <div className="flex items-center gap-1">
                              {comp.origin === "Live Discovery" || comp.pending_review ? (
                                <Badge variant="outline" className="text-2xs bg-amber-500/10 text-amber-500 border-amber-500/30">
                                  Pending Review
                                </Badge>
                              ) : (
                                <Badge variant="outline" className="text-2xs bg-emerald-500/10 text-emerald-600 border-emerald-500/30">
                                  Verified DB
                                </Badge>
                              )}
                              {comp.email_status === "VERIFIED" && (
                                <Badge variant="outline" className="text-2xs bg-blue-500/10 text-blue-500 border-blue-500/30">
                                  Email Verified
                                </Badge>
                              )}
                            </div>
                          </div>

                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-muted-foreground text-xs">
                            {(comp.address_city || comp.address_state) && (
                              <div className="flex items-center gap-1.5">
                                <MapPin className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                                <span>{comp.address_city ? `${comp.address_city}, ` : ""}{comp.address_state || ""}</span>
                              </div>
                            )}

                            {(comp.website || comp.domain) && (
                              <div className="flex items-center gap-1.5">
                                <Globe className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                                <a
                                  href={comp.website?.startsWith("http") ? comp.website : `https://${comp.website || comp.domain}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-primary hover:underline truncate"
                                >
                                  {comp.domain || comp.website}
                                </a>
                              </div>
                            )}

                            {comp.phone && (
                              <div className="flex items-center gap-1.5">
                                <Phone className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                                <span>{comp.phone}</span>
                              </div>
                            )}

                            {comp.email && (
                              <div className="flex items-center gap-1.5">
                                <Mail className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                                <span className="truncate">{comp.email}</span>
                              </div>
                            )}

                            {comp.executive && (
                              <div className="flex items-center gap-1.5 col-span-2 text-foreground font-medium">
                                <User className="w-3 h-3 text-primary flex-shrink-0" />
                                <span>{comp.executive}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {msg.role === "user" && (
                <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center flex-shrink-0 text-primary-foreground mt-1">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          ))}

          {/* ── Active Streaming Steps Collapsible Accordion ───────────────── */}
          {isStreaming && (
            <div className="max-w-4xl mx-auto bg-card border rounded-lg p-3 space-y-2">
              <div
                className="flex items-center justify-between cursor-pointer"
                onClick={() => setShowSteps(!showSteps)}
              >
                <div className="flex items-center gap-2 text-xs font-semibold text-primary">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Agent Reasoning & Extraction Pipeline</span>
                </div>
                {showSteps ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              </div>

              {showSteps && (
                <div className="space-y-1.5 pt-1 border-t">
                  {streamSteps.map((step, idx) => (
                    <div key={idx} className="flex items-start gap-2 text-xs">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" />
                      <div>
                        <span className="font-medium text-foreground">{step.title}</span>
                        {step.event === "search_plan" && step.data.explanation && (
                          <div className="text-2xs text-muted-foreground">{step.data.explanation}</div>
                        )}
                        {step.event === "database_results" && (
                          <div className="text-2xs text-muted-foreground">Found {step.data.count} existing database records</div>
                        )}
                        {step.event === "live_discovery_started" && (
                          <div className="text-2xs text-amber-500">
                            Invoked Live Discovery ({step.data.reason})
                          </div>
                        )}
                        {step.event === "saving_for_review" && (
                          <div className="text-2xs text-emerald-600 font-medium">
                            Staged {step.data.count} new attributes in Review Queue (PENDING)
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* ── Sticky Input Bar ─────────────────────────────────────────────── */}
        <div className="p-3 border-t bg-card">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendMessage();
            }}
            className="max-w-4xl mx-auto flex items-center gap-2"
          >
            <Input
              value={inputPrompt}
              onChange={(e) => setInputPrompt(e.target.value)}
              placeholder="Ask anything (e.g. 'Find healthcare companies in Dallas with emails and phone numbers')..."
              disabled={isStreaming}
              className="text-xs h-10"
            />
            {isStreaming ? (
              <Button type="button" variant="destructive" size="sm" className="h-10 px-4 gap-1.5" onClick={handleStop}>
                <StopCircle className="w-4 h-4" />
                Stop
              </Button>
            ) : (
              <Button type="submit" size="sm" disabled={!inputPrompt.trim()} className="h-10 px-4 gap-1.5">
                <Send className="w-4 h-4" />
                Search
              </Button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
