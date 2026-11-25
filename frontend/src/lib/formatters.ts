/**
 * Shared enterprise formatters and visual signal helpers.
 * Single source of truth for currency, headcount, trust normalization, and sync timestamps.
 */

export function normalizePercentScore(raw: number | null | undefined, fallback = 85): number {
  if (raw === null || raw === undefined || Number.isNaN(Number(raw))) {
    return fallback;
  }
  const num = Number(raw);
  const pct = num <= 1 && num > 0 ? Math.round(num * 100) : Math.round(num);
  return Math.max(0, Math.min(100, pct));
}

export function formatRevenueBadge(usd: number | null | undefined): string {
  if (!usd || usd <= 0) return "Unreported";
  if (usd >= 1_000_000_000) return `$${(usd / 1_000_000_000).toFixed(1)}B`;
  if (usd >= 1_000_000) return `$${(usd / 1_000_000).toFixed(1)}M`;
  if (usd >= 1_000) return `$${Math.round(usd / 1_000)}K`;
  return `$${usd.toLocaleString("en-US")}`;
}

export function formatEmployeeBadge(
  min?: number | null,
  max?: number | null,
  band?: string | null
): string {
  if (band && band.trim()) return `${band.trim()} emp`;
  if (min && max) {
    if (min === max) return `${min.toLocaleString("en-US")} emp`;
    return `${min.toLocaleString("en-US")}–${max.toLocaleString("en-US")} emp`;
  }
  if (min && min > 0) return `${min.toLocaleString("en-US")}+ emp`;
  if (max && max > 0) return `Up to ${max.toLocaleString("en-US")}`;
  return "Size N/A";
}

export function formatRelativeSync(isoDate?: string | null): string {
  if (!isoDate) return "Synced";
  const ts = Date.parse(isoDate);
  if (Number.isNaN(ts)) return "Synced";

  const diffMs = Date.now() - ts;
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;

  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;

  const diffDays = Math.floor(diffHr / 24);
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 30) return `${diffDays}d ago`;

  return new Date(ts).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatSourceLabel(rawSource: string): string {
  return rawSource
    .replace("_NPI", "")
    .replace("_EDGAR", "")
    .replace("PROPUBLICA_990", "ProPublica")
    .replace("PROPUBLICA", "ProPublica")
    .replace("FDIC_BANKS", "FDIC")
    .replace("OPEN_DIRECTORIES_SF", "Open Directories")
    .replace("100K_LOAD_BENCHMARK", "Registry Benchmark")
    .replace("USASPENDING", "USASpending")
    .replace("OPENSTREETMAP", "OpenStreetMap")
    .replace("GOOGLE_MAPS", "Google Maps")
    .replace("INTERNAL_JSON", "Master Vault");
}
