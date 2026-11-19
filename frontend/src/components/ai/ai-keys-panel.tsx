"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, Plus, Trash2, FlaskConical, RefreshCw, KeyRound } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

type Provider = "groq" | "aws";

interface KeyRow {
  id: string;
  provider: string;
  label: string;
  masked: string;
  status: "active" | "disabled" | "invalid" | "expired";
  priority: number;
  expires_at: string | null;
  cooldown_until: string | null;
  fail_count: number;
  last_used_at: string | null;
}

interface LlmStatus {
  provider: string;
  fallback_chain: string[];
  models: Record<string, string>;
  groq_key_available: boolean;
  groq_key_source: string | null;
  groq_key_masked: string | null;
  budget: { daily_token_budget: number; tokens_used_today: number | null; unlimited: boolean };
}

const STATUS_STYLE: Record<KeyRow["status"], "default" | "secondary" | "destructive" | "outline"> = {
  active: "default",
  disabled: "secondary",
  invalid: "destructive",
  expired: "outline",
};

function fmt(ts: string | null): string {
  return ts ? new Date(ts).toLocaleString() : "never";
}

export function AiKeysPanel() {
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const [status, setStatus] = useState<LlmStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  // Form state. The key value is write-only and is cleared right after submit.
  const [provider, setProvider] = useState<Provider>("groq");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");
  const [priority, setPriority] = useState("10");
  const [expiry, setExpiry] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [k, s] = await Promise.all([
        api.get<{ keys: KeyRow[] }>("/v1/secrets/keys"),
        api.get<LlmStatus>("/v1/llm/status"),
      ]);
      setKeys(k.keys);
      setStatus(s);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load keys");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function addKey(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setSaving(true);
    try {
      await api.post("/v1/secrets/keys", {
        provider,
        value: value.trim(),
        label: label.trim(),
        priority: Number(priority) || 100,
        expires_at: expiry ? new Date(expiry).toISOString() : null,
      });
      toast.success("Key saved. It is used immediately, no restart needed.");
      setLabel("");
      setExpiry("");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save key");
    } finally {
      setValue(""); // never keep the secret in component state after submit
      setSaving(false);
    }
  }

  async function act(id: string, kind: "test" | "toggle" | "delete", row?: KeyRow) {
    setBusy(id);
    try {
      if (kind === "test") {
        const res = await api.post<{ ok: boolean | null; status_code?: number; detail?: string }>(
          `/v1/secrets/keys/${id}/test`,
          {},
        );
        if (res.ok) toast.success("Key works");
        else toast.error(res.detail ?? `Key rejected (HTTP ${res.status_code ?? "?"})`);
      } else if (kind === "toggle" && row) {
        await api.patch(`/v1/secrets/keys/${id}`, {
          status: row.status === "active" ? "disabled" : "active",
        });
      } else if (kind === "delete") {
        await api.delete(`/v1/secrets/keys/${id}`);
        toast.success("Key deleted");
      }
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI Keys</h1>
          <p className="text-sm text-muted-foreground">
            Add a new key each day. Keys are encrypted at rest and the platform switches to the next key
            automatically when one is rejected or rate limited.
          </p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={loading}>
          {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />} Refresh
        </Button>
      </div>

      {status && (
        <Card>
          <CardHeader>
            <CardTitle>Active LLM</CardTitle>
            <CardDescription>
              Provider <b>{status.provider}</b>
              {status.fallback_chain.length > 0 && <> then {status.fallback_chain.join(", ")}</>}
              {" · model "}
              <b>{status.models[status.provider] ?? "n/a"}</b>
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3 text-sm">
            <Badge variant={status.groq_key_available ? "default" : "destructive"}>
              {status.groq_key_available
                ? `Groq key in use: ${status.groq_key_masked} (${status.groq_key_source})`
                : "No usable Groq key"}
            </Badge>
            <Badge variant="outline">
              Tokens today: {status.budget.tokens_used_today ?? "unknown"}
              {status.budget.unlimited ? " (no daily limit)" : ` / ${status.budget.daily_token_budget}`}
            </Badge>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" /> Add key
          </CardTitle>
          <CardDescription>
            The value is sent once and cannot be viewed again. Lower priority numbers are used first.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={addKey} className="grid gap-4 md:grid-cols-6">
            <div className="space-y-1 md:col-span-1">
              <Label htmlFor="provider">Provider</Label>
              <select
                id="provider"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={provider}
                onChange={(e) => setProvider(e.target.value as Provider)}
              >
                <option value="groq">Groq</option>
                <option value="aws">AWS (JSON credentials)</option>
              </select>
            </div>
            <div className="space-y-1 md:col-span-1">
              <Label htmlFor="label">Label</Label>
              <Input id="label" placeholder="monday" value={label} onChange={(e) => setLabel(e.target.value)} />
            </div>
            <div className="space-y-1 md:col-span-2">
              <Label htmlFor="value">Key</Label>
              <Input
                id="value"
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder={provider === "groq" ? "gsk_..." : '{"access_key_id":"...","secret_access_key":"..."}'}
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            </div>
            <div className="space-y-1 md:col-span-1">
              <Label htmlFor="priority">Priority</Label>
              <Input id="priority" type="number" min={1} max={1000} value={priority}
                     onChange={(e) => setPriority(e.target.value)} />
            </div>
            <div className="space-y-1 md:col-span-1">
              <Label htmlFor="expiry">Expires</Label>
              <Input id="expiry" type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
            </div>
            <div className="md:col-span-6">
              <Button type="submit" disabled={saving || value.trim().length < 8}>
                {saving ? <Loader2 className="animate-spin" /> : <Plus />} Save key
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Stored keys</CardTitle>
        </CardHeader>
        <CardContent>
          {keys.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No keys stored in the database. Keys from the environment or AWS Secrets Manager are used if present.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="keys-table">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-2 pr-4">Provider</th>
                    <th className="pr-4">Label</th>
                    <th className="pr-4">Key</th>
                    <th className="pr-4">Status</th>
                    <th className="pr-4">Priority</th>
                    <th className="pr-4">Expires</th>
                    <th className="pr-4">Last used</th>
                    <th className="pr-4">Failures</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {keys.map((k) => (
                    <tr key={k.id} className="border-b last:border-0">
                      <td className="py-2 pr-4">{k.provider}</td>
                      <td className="pr-4">{k.label || "-"}</td>
                      <td className="pr-4 font-mono">{k.masked}</td>
                      <td className="pr-4">
                        <Badge variant={STATUS_STYLE[k.status]}>{k.status}</Badge>
                        {k.cooldown_until && new Date(k.cooldown_until) > new Date() && (
                          <span className="ml-2 text-xs text-amber-500">cooling down</span>
                        )}
                      </td>
                      <td className="pr-4">{k.priority}</td>
                      <td className="pr-4">{k.expires_at ? new Date(k.expires_at).toLocaleDateString() : "-"}</td>
                      <td className="pr-4">{fmt(k.last_used_at)}</td>
                      <td className="pr-4">{k.fail_count}</td>
                      <td className="space-x-2 whitespace-nowrap text-right">
                        <Button size="sm" variant="outline" disabled={busy === k.id || k.provider !== "groq"}
                                onClick={() => void act(k.id, "test")}>
                          <FlaskConical /> Test
                        </Button>
                        <Button size="sm" variant="outline" disabled={busy === k.id}
                                onClick={() => void act(k.id, "toggle", k)}>
                          {k.status === "active" ? "Disable" : "Enable"}
                        </Button>
                        <Button size="sm" variant="destructive" disabled={busy === k.id}
                                onClick={() => void act(k.id, "delete")}>
                          <Trash2 />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
