import Link from "next/link";
import { FileQuestion, LayoutDashboard, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-6 text-foreground">
      <div className="max-w-md w-full rounded-xl border border-border/80 bg-card p-6 shadow-lg text-center space-y-4">
        <div className="w-12 h-12 rounded-full bg-primary/10 text-primary flex items-center justify-center mx-auto border border-primary/20">
          <FileQuestion className="w-6 h-6" />
        </div>
        <div className="space-y-1">
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            Page Not Found
          </h1>
          <p className="text-xs text-muted-foreground leading-relaxed">
            The requested resource or route does not exist or has been moved.
          </p>
        </div>

        <div className="flex items-center justify-center gap-3 pt-2">
          <Button
            asChild
            size="sm"
            className="gap-1.5 font-medium shadow-sm"
          >
            <Link href="/dashboard">
              <LayoutDashboard className="w-3.5 h-3.5" /> Dashboard
            </Link>
          </Button>
          <Button
            asChild
            variant="outline"
            size="sm"
            className="gap-1.5 font-medium border-border/80"
          >
            <Link href="/leads">
              <ArrowLeft className="w-3.5 h-3.5" /> Master Vault
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
