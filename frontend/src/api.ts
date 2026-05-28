import { useState, useEffect, useCallback } from "react";
import type { StatsPayload } from "./types";

interface UseStatsResult {
  stats: StatsPayload | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useStats(statsPath?: string): UseStatsResult {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/?$/, "/");
  const resolvedPath = statsPath ?? `${base}stats.json`;
  const [stats, setStats] = useState<StatsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch(`${resolvedPath}?t=${Date.now()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data: StatsPayload = await res.json();
      setStats(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load stats";
      setError(msg);
    }
  }, [resolvedPath]);

  useEffect(() => {
    fetchStats().finally(() => setLoading(false));
    const interval = setInterval(fetchStats, 30_000);
    return () => clearInterval(interval);
  }, [fetchStats]);

  const refetch = useCallback(() => {
    setLoading(true);
    fetchStats().finally(() => setLoading(false));
  }, [fetchStats]);

  return { stats, loading, error, refetch };
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pt-PT", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
  return n.toLocaleString("pt-PT");
}

export function pct(n: number | null | undefined, decimals = 1): string {
  if (n == null) return "—";
  return (n * 100).toFixed(decimals) + "%";
}
