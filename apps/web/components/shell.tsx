"use client";

import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// ---------------- async hook + states ----------------
export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  notFound: boolean;
  /** A connection failure is being retried automatically (data, if any, stays). */
  retrying: boolean;
  reload: () => void;
}

const MAX_AUTO_RETRIES = 5;

/**
 * Data hook with self-healing. A connection failure (ApiError status 0 — the API
 * is restarting / briefly unreachable) does NOT surface a hard error: the
 * last-known-good data stays on screen and the request auto-retries with backoff
 * (1s→8s, then a calm 15s heartbeat), so the page recovers on its own without a
 * manual refresh. Only a deterministic HTTP error (4xx/5xx) is terminal; a 404
 * sets notFound.
 */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  // Always call the latest closure from the retry timer.
  const fnRef = useRef(fn);
  fnRef.current = fn;
  // Whether we've ever loaded data — gates the spinner and the error banner so a
  // background reconnect never blanks the screen.
  const hasData = useRef(false);

  useEffect(() => {
    let alive = true;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const run = () => {
      if (!hasData.current) setLoading(true);
      fnRef.current()
        .then((d) => {
          if (!alive) return;
          attempt = 0;
          hasData.current = true;
          setData(d);
          setError(null);
          setNotFound(false);
          setRetrying(false);
          setLoading(false);
        })
        .catch((e) => {
          if (!alive) return;
          setLoading(false);
          if (e instanceof ApiError && e.status === 404) {
            setNotFound(true);
            setError(null);
            setRetrying(false);
            return;
          }
          const isConnection = e instanceof ApiError && e.status === 0;
          if (isConnection) {
            attempt += 1;
            setRetrying(true);
            // Keep last-known-good data visible; only show the note if we have nothing.
            if (!hasData.current) setError(e instanceof Error ? e.message : String(e));
            const delay = attempt <= MAX_AUTO_RETRIES
              ? Math.min(8000, 1000 * 2 ** (attempt - 1)) // 1s,2s,4s,8s,8s
              : 15000;                                     // calm heartbeat for longer outages
            timer = setTimeout(run, delay);
          } else {
            // Deterministic HTTP / parse error — terminal.
            setError(e instanceof Error ? e.message : String(e));
            setRetrying(false);
          }
        });
    };

    run();
    return () => { alive = false; if (timer) clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, ...deps]);

  return { data, error, loading, notFound, retrying, reload };
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Loading() {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2 p-8 text-sm text-muted" role="status" aria-live="polite">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {t("loading")}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-elevated/70", className)} aria-hidden />;
}

export function ErrorNote({ error }: { error: string }) {
  const { t } = useI18n();
  // A connection failure (API restarting / briefly unreachable) is auto-retried
  // by useApi — show a calm "reconnecting" note, not a scary red error.
  const isConnection = error.startsWith("API unreachable") || error.startsWith("API gateway");
  if (isConnection) {
    return (
      <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm text-warning" role="status" aria-live="polite">
        <p className="flex items-center gap-2 font-semibold">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {t("reconnecting")}
        </p>
        <p className="mt-1 text-xs text-muted">{t("reconnecting_hint")}</p>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-danger" role="alert">
      <p className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" aria-hidden /> {t("request_failed")}</p>
      <p className="mt-1 break-all font-mono text-xs">{error}</p>
    </div>
  );
}

export function EmptyState({ note, onAction, actionLabel }: { note: string; onAction?: () => void; actionLabel?: string }) {
  return (
    <div className="card flex flex-col items-start gap-3">
      <p className="text-sm text-muted">{note}</p>
      {onAction && <button className="btn" onClick={onAction}><RefreshCw className="h-3.5 w-3.5" /> {actionLabel ?? "Retry"}</button>}
    </div>
  );
}

// ---------------- badges & status ----------------
const STATUS_STYLE: Record<string, string> = {
  REAL_TIME: "border-up/40 text-up",
  DELAYED: "border-accent/40 text-accent",
  END_OF_DAY: "border-accent/40 text-accent",
  PROXY: "border-warning/40 text-warning",
  ESTIMATED: "border-warning/40 text-warning",
  STALE: "border-warning/50 text-warning",
  UNAVAILABLE: "border-muted/40 text-muted",
  MOCK: "border-danger/50 text-danger",
};

const STATUS_KO: Record<string, string> = {
  REAL_TIME: "실시간", DELAYED: "지연 시세", END_OF_DAY: "종가 기준", ESTIMATED: "추정",
  STALE: "오래된 값", UNAVAILABLE: "데이터 없음", MOCK: "모의 데이터",
};
export function StatusBadge({ status }: { status: string }) {
  const { lang } = useI18n();
  const label = lang === "ko" ? STATUS_KO[status] ?? status : status;
  return (
    <span className={cn("chip", STATUS_STYLE[status] ?? "text-muted")} title={`Data status: ${status}`}>
      <span aria-hidden>●</span> {label}
    </span>
  );
}

const QUALITY_STYLE: Record<string, string> = {
  fresh: "border-up/40 text-up", mixed: "border-warning/40 text-warning", stale: "border-danger/40 text-danger",
};
const QUALITY_KO: Record<string, string> = { fresh: "최신", mixed: "일부 지연", stale: "오래됨" };
export function QualityBadge({ quality }: { quality: string }) {
  const { lang } = useI18n();
  const label = lang === "ko" ? QUALITY_KO[quality] ?? quality : quality;
  return <span className={cn("chip", QUALITY_STYLE[quality] ?? "text-muted")}>{label}</span>;
}

const ACTION_STYLE: Record<string, string> = {
  strong_buy: "border-up/60 bg-up/15 text-up",
  buy: "border-up/50 bg-up/10 text-up",
  accumulate: "border-up/40 bg-up/5 text-up",
  hold: "border-border text-muted",
  watch: "border-accent/50 bg-accent/10 text-accent",
  reduce: "border-warning/50 bg-warning/10 text-warning",
  sell: "border-down/50 bg-down/10 text-down",
  avoid: "border-down/60 bg-down/15 text-down",
};
const ACTION_KO: Record<string, string> = {
  strong_buy: "강한 매수", buy: "매수", accumulate: "분할매수", hold: "보유",
  watch: "관망", reduce: "비중축소", sell: "매도", avoid: "회피",
};
export function ActionBadge({ action, lang }: { action: string; lang: "en" | "ko" }) {
  const label = lang === "ko" ? ACTION_KO[action] ?? action : action.replace("_", " ").toUpperCase();
  return <span className={cn("inline-flex rounded-md border px-2 py-0.5 text-xs font-semibold", ACTION_STYLE[action] ?? "border-border")}>{label}</span>;
}

const QUADRANT_STYLE: Record<string, string> = {
  LEADING: "border-up/50 bg-up/10 text-up",
  IMPROVING: "border-accent/50 bg-accent/10 text-accent",
  WEAKENING: "border-warning/50 bg-warning/10 text-warning",
  LAGGING: "border-down/50 bg-down/10 text-down",
};
export function QuadrantBadge({ q }: { q: string }) {
  return <span className={cn("inline-flex rounded-md border px-2 py-0.5 text-xs font-medium", QUADRANT_STYLE[q] ?? "border-border")}>{q}</span>;
}

/** Signed bar centered at 0 (e.g. regime score -100..100 or direction -1..1). */
export function LeanBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.max(-1, Math.min(1, value / max)) * 50;
  const left = pct >= 0 ? 50 : 50 + pct;
  const width = Math.abs(pct);
  const color = value > 0.5 ? "bg-up" : value < -0.5 ? "bg-down" : "bg-muted";
  return (
    <div className="relative h-2 w-full rounded-full bg-elevated" role="img" aria-label={`score ${value}`}>
      <div className="absolute left-1/2 top-0 h-2 w-px -translate-x-1/2 bg-border" />
      <div className={cn("absolute top-0 h-2 rounded-full", color)} style={{ left: `${left}%`, width: `${width}%` }} />
    </div>
  );
}
