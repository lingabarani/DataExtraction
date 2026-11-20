"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Filter,
  Globe,
  Loader2,
  Mail,
  Phone,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  User,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { chatApi, ChatReviewItem } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export default function ReviewQueuePage() {
  const [reviews, setReviews] = useState<ChatReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeFilter, setActiveFilter] = useState<string>("PENDING");
  const [searchQuery, setSearchQuery] = useState("");
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  const loadReviews = useCallback(async () => {
    setLoading(true);
    try {
      const statusParam = activeFilter === "ALL" ? undefined : activeFilter;
      const data = await chatApi.listReviews({ status: statusParam, limit: 100 });
      setReviews(data);
    } catch {
      toast.error("Failed to load review items");
    } finally {
      setLoading(false);
    }
  }, [activeFilter]);

  useEffect(() => {
    loadReviews();
  }, [loadReviews]);

  const handleApprove = async (id: string) => {
    setActionInProgress(id);
    try {
      await chatApi.approveReview(id, "Approved via Web UI");
      setReviews((prev) =>
        prev.map((r) => (r.id === id ? { ...r, review_status: "APPROVED" } : r))
      );
      toast.success("Discovery approved and promoted to golden records");
    } catch (err: any) {
      toast.error("Failed to approve review item");
    } finally {
      setActionInProgress(null);
    }
  };

  const handleReject = async (id: string) => {
    const reason = window.prompt("Enter rejection reason (optional):", "Incorrect or unverified source");
    if (reason === null) return;

    setActionInProgress(id);
    try {
      await chatApi.rejectReview(id, reason);
      setReviews((prev) =>
        prev.map((r) => (r.id === id ? { ...r, review_status: "REJECTED", rejection_reason: reason } : r))
      );
      toast.info("Discovery rejected (canonical data unchanged)");
    } catch (err: any) {
      toast.error("Failed to reject review item");
    } finally {
      setActionInProgress(null);
    }
  };

  const filteredReviews = reviews.filter((r) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      r.company_name?.toLowerCase().includes(q) ||
      r.field_name?.toLowerCase().includes(q) ||
      r.source_type?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-emerald-500" />
            Chatbot Discovery Review Queue
          </h1>
          <p className="text-xs text-muted-foreground mt-1">
            Audit and approve newly discovered attributes before they are promoted into canonical company records.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={loadReviews} disabled={loading} className="h-8 gap-1.5 text-xs">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Link href="/chat">
            <Button size="sm" className="h-8 text-xs">
              Back to AI Chat
            </Button>
          </Link>
        </div>
      </div>

      {/* Filter Tabs & Search */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 border-b pb-4">
        <div className="flex rounded-md border p-0.5 bg-muted/40 w-full sm:w-auto">
          {["PENDING", "APPROVED", "REJECTED", "ALL"].map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveFilter(tab)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                activeFilter === tab
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        <div className="relative w-full sm:w-72">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by company or field..."
            className="h-8 text-xs pl-8"
          />
        </div>
      </div>

      {/* Review Items Grid */}
      {loading ? (
        <div className="py-20 text-center space-y-2">
          <Loader2 className="w-6 h-6 animate-spin mx-auto text-primary" />
          <p className="text-xs text-muted-foreground">Loading staged discoveries...</p>
        </div>
      ) : filteredReviews.length === 0 ? (
        <div className="py-20 text-center border rounded-lg bg-card/40 space-y-3">
          <ShieldCheck className="w-10 h-10 mx-auto text-muted-foreground" />
          <h3 className="text-sm font-semibold">No Review Items</h3>
          <p className="text-xs text-muted-foreground max-w-sm mx-auto">
            There are no discoveries matching the current filter ({activeFilter}). Newly discovered facts from the AI Chatbot will appear here for review.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {filteredReviews.map((item) => (
            <Card key={item.id} className="overflow-hidden border shadow-sm">
              <CardHeader className="py-3 px-4 bg-muted/20 border-b flex flex-row items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm">{item.company_name}</span>
                  <Badge variant="outline" className="text-2xs uppercase tracking-wider">
                    {item.field_name}
                  </Badge>
                  {item.verification_status === "CONFLICTING" && (
                    <Badge variant="destructive" className="text-2xs gap-1">
                      <AlertCircle className="w-3 h-3" /> Conflicting
                    </Badge>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-2xs text-muted-foreground">
                    Confidence: {Math.round(item.field_confidence * 100)}%
                  </span>
                  <Badge
                    variant={
                      item.review_status === "APPROVED"
                        ? "default"
                        : item.review_status === "REJECTED"
                        ? "destructive"
                        : "secondary"
                    }
                    className="text-2xs"
                  >
                    {item.review_status}
                  </Badge>
                </div>
              </CardHeader>

              <CardContent className="p-4 space-y-3">
                {/* Diff Viewer */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-3 rounded-md bg-muted/30 border text-xs">
                  <div>
                    <span className="text-2xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1">
                      Existing Database Value
                    </span>
                    <div className="p-2 rounded bg-background border text-muted-foreground font-mono truncate">
                      {item.existing_value ? JSON.stringify(item.existing_value) : "<Empty / Missing>"}
                    </div>
                  </div>

                  <div>
                    <span className="text-2xs font-semibold text-primary uppercase tracking-wider block mb-1">
                      Newly Discovered Value
                    </span>
                    <div className="p-2 rounded bg-background border text-primary font-mono font-medium truncate">
                      {typeof item.discovered_value === "object"
                        ? JSON.stringify(item.discovered_value)
                        : String(item.discovered_value)}
                    </div>
                  </div>
                </div>

                {/* Evidence & Provenance */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between text-xs text-muted-foreground gap-2 pt-1">
                  <div className="flex items-center gap-3">
                    <span>Source: <strong className="text-foreground">{item.source_type}</strong></span>
                    {item.source_url && (
                      <a
                        href={item.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary hover:underline"
                      >
                        Source Link <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>

                  {item.evidence && (
                    <span className="text-2xs italic truncate max-w-md">
                      Evidence: &quot;{item.evidence}&quot;
                    </span>
                  )}
                </div>

                {item.rejection_reason && (
                  <div className="text-2xs text-red-500 font-medium">
                    Rejection Reason: {item.rejection_reason}
                  </div>
                )}

                {/* Action Controls for PENDING items */}
                {item.review_status === "PENDING" && (
                  <div className="flex items-center justify-end gap-2 pt-2 border-t">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={actionInProgress === item.id}
                      onClick={() => handleReject(item.id)}
                      className="h-8 gap-1.5 text-xs text-destructive hover:bg-destructive/10"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      Reject
                    </Button>

                    <Button
                      size="sm"
                      disabled={actionInProgress === item.id}
                      onClick={() => handleApprove(item.id)}
                      className="h-8 gap-1.5 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                    >
                      {actionInProgress === item.id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      )}
                      Approve & Promote
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
