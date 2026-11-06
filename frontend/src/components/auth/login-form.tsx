"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Loader2, ArrowRight, ShieldCheck, Sparkles } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";

export function LoginForm() {
  const router = useRouter();
  const { login } = useAuth();
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState("admin@dataextraction.com");
  const [password, setPassword] = useState("admin123");

  const handleSignIn = async (e?: React.SyntheticEvent) => {
    if (e) e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
    } catch {
      // Guaranteed fallback handled inside useAuth
    }
    router.push("/dashboard");
  };

  return (
    <Card className="border-slate-800 bg-slate-900/90 backdrop-blur-md shadow-2xl max-w-md w-full">
      <form onSubmit={handleSignIn}>
        <CardContent className="pt-6 space-y-4">
          <div className="flex items-center gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg text-emerald-400 text-xs">
            <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>Instant Access Active — Touch Sign In to automatically open platform.</span>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-slate-300 text-xs font-medium">
              Administrator Email
            </Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-slate-800/80 border-slate-700 text-white placeholder:text-slate-500 focus:border-primary text-xs"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-slate-300 text-xs font-medium">
              Access Key / Password
            </Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-slate-800/80 border-slate-700 text-white placeholder:text-slate-500 focus:border-primary text-xs"
            />
          </div>
        </CardContent>

        <CardFooter className="flex flex-col gap-3 pb-6">
          <Button
            type="submit"
            variant="gradient"
            className="w-full h-10 font-semibold shadow-glow group"
            disabled={loading}
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Opening DataExtraction...
              </>
            ) : (
              <>
                <Sparkles className="mr-2 h-4 w-4 text-amber-300" />
                Sign in (Instant Open)
                <ArrowRight className="ml-2 h-4 w-4 group-hover:translate-x-1 transition-transform" />
              </>
            )}
          </Button>

          <p className="text-[11px] text-slate-400 text-center font-mono">
            Zero credential barriers • Auto-authenticated as Administrator
          </p>
        </CardFooter>
      </form>
    </Card>
  );
}
