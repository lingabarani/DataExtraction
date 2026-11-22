"use client";

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle, RefreshCw, LayoutDashboard } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log exception to client monitoring
    console.error("Application runtime error captured by boundary:", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6 text-foreground">
      <div className="max-w-md w-full rounded-xl border border-destructive/30 bg-card p-6 shadow-lg text-center space-y-4">
        <div className="w-12 h-12 rounded-full bg-destructive/10 text-destructive flex items-center justify-center mx-auto border border-destructive/20">
          <AlertTriangle className="w-6 h-6" />
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-bold tracking-tight text-foreground">
            Something unexpected occurred
          </h2>
          <p className="text-xs text-muted-foreground leading-relaxed">
            The application encountered a recoverable runtime error. Your session data remains safe.
          </p>
        </div>

        {error.message && (
          <div className="text-left bg-muted/50 border border-border/60 rounded-md p-3 text-xs font-mono text-muted-foreground break-all max-h-32 overflow-y-auto">
            {error.message}
          </div>
        )}

        <div className="flex items-center justify-center gap-3 pt-2">
          <Button
            onClick={() => reset()}
            size="sm"
            className="gap-1.5 font-medium shadow-sm"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Try Again
          </Button>
          <Button
            asChild
            variant="outline"
            size="sm"
            className="gap-1.5 font-medium border-border/80"
          >
            <Link href="/dashboard">
              <LayoutDashboard className="w-3.5 h-3.5" /> Dashboard
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
