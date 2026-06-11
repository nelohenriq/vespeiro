import { useState, useEffect, useCallback, useRef } from "react";
import type {
  OverviewResponse,
  JusticeResponse,
  ProcurementResponse,
  SocialResponse,
  CrossRefResponse,
  HealthResponse,
  TransparencyResponse,
} from "./types";

const API_BASE = "/api";
const REFRESH_INTERVAL = 60_000; // 1 minute

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
  lastUpdated: string | null;
}

function useApi<T>(
  endpoint: string,
  autoRefresh = true,
  intervalMs: number = REFRESH_INTERVAL,
  skip: boolean = false
): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(!skip);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchData = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        signal: controller.signal,
      });
      if (!res.ok) {
        // Try to extract a friendly error message from the proxy's JSON body
        const body = await res.json().catch(() => null);
        const msg =
          (body && typeof body.error === "string" && body.error) ||
          (body && typeof body.detail === "string" && body.detail) ||
          `HTTP ${res.status}: ${res.statusText}`;
        throw new Error(msg);
      }
      const json: T = await res.json();
      setData(json);
      setLastUpdated(new Date().toLocaleTimeString("pt-PT"));
      setError(null);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "Failed to fetch");
    }
  }, [endpoint, skip]);

  // Keep latest fetchData and data in refs so the initial-fetch effect
  // doesn't need to depend on them (avoids re-running on every change,
  // which would cause an infinite re-fetch loop on successful responses).
  const fetchDataRef = useRef(fetchData);
  const dataRef = useRef(data);
  useEffect(() => { fetchDataRef.current = fetchData; }, [fetchData]);
  useEffect(() => { dataRef.current = data; }, [data]);

  useEffect(() => {
    if (skip) {
      // Skip fetching entirely — keep idle state
      setLoading(false);
      return;
    }
    // Initial fetch on mount (or when skip flips true→false).
    // Only show loading spinner if we have no stale data to display.
    if (!dataRef.current) setLoading(true);
    fetchDataRef.current().finally(() => setLoading(false));
  }, [endpoint, skip]);

  useEffect(() => {
    if (skip || !autoRefresh) return;
    // Interval setup — changing intervalMs only resets the timer, no extra fetch
    const interval = setInterval(fetchData, intervalMs);
    return () => clearInterval(interval);
  }, [fetchData, autoRefresh, intervalMs, skip]);

  // Cleanup any in-flight fetch on unmount
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const refetch = useCallback(() => {
    if (skip) return;
    setLoading(true);
    fetchData().finally(() => setLoading(false));
  }, [fetchData, skip]);

  return { data, loading, error, refetch, lastUpdated };
}

// ── Domain-specific hooks ───────────────────────────────────────────────────

export function useOverview(skip: boolean = false) {
  return useApi<OverviewResponse>("/overview", true, REFRESH_INTERVAL, skip);
}

export function useJustice(skip: boolean = false) {
  return useApi<JusticeResponse>("/justice", true, REFRESH_INTERVAL, skip);
}

export function useProcurement(skip: boolean = false) {
  return useApi<ProcurementResponse>("/procurement", true, REFRESH_INTERVAL, skip);
}

export function useSocial(skip: boolean = false) {
  return useApi<SocialResponse>("/social", true, REFRESH_INTERVAL, skip);
}

export function useCrossRef(skip: boolean = false) {
  return useApi<CrossRefResponse>("/crossref", true, REFRESH_INTERVAL, skip);
}

export function useHealth(skip: boolean = false) {
  return useApi<HealthResponse>("/health", true, REFRESH_INTERVAL, skip);
}

/**
 * Lightweight health probe for the live status banner.
 * Polls /api/health every 5 seconds when the API is online.
 * Backs off to 15 seconds after consecutive failures to avoid hammering a dead server.
 * Returns to 5 seconds once the API recovers.
 * Distinct from useHealth() which uses the 60s default interval and drives the Health tab.
 */
export function useHealthPoll() {
  const [intervalMs, setIntervalMs] = useState(5_000);
  const result = useApi<HealthResponse>("/health", true, intervalMs);

  useEffect(() => {
    if (result.error) {
      // Exponential backoff when the API is down: 5s → 10s → 20s → 30s (cap)
      setIntervalMs((prev) => Math.min(prev * 2, 30_000));
    } else if (result.data) {
      // Reset to fast polling once the API is reachable
      setIntervalMs(5_000);
    }
  }, [result.error, result.data]);

  return result;
}

export function useTransparency() {
  return useApi<TransparencyResponse>("/transparency");
}

// ── Formatters ──────────────────────────────────────────────────────────────

export function fmtNum(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + "B";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return n.toLocaleString("pt-PT");
}

export function fmtEur(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000_000) return "\u20AC" + (n / 1_000_000_000).toFixed(1) + "B";
  if (n >= 1_000_000) return "\u20AC" + (n / 1_000_000).toFixed(0) + "M";
  if (n >= 1_000) return "\u20AC" + (n / 1_000).toFixed(0) + "K";
  return "\u20AC" + n.toLocaleString("pt-PT");
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toFixed(1) + "%";
}

export function fmtYear(n: number | null | undefined): string {
  if (n == null) return "—";
  return String(n);
}
