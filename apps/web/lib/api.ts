// Typed API client — single source of truth for frontend<->backend contracts.

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// --- Static mode (CDN deploy, no live server) --------------------------------
// When built with NEXT_PUBLIC_STATIC_MODE=1, GETs are served from pre-baked JSON
// snapshots under `${BASE_PATH}/data/...` (produced by apps/snapshot/main.py)
// instead of a live API. This lets the whole site run from a static host
// (GitHub Pages) 24/7, independent of any running computer.
export const STATIC_MODE = process.env.NEXT_PUBLIC_STATIC_MODE === "1";
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** Map a live API path (+query) to its baked snapshot file. MUST match the
 * encoding in apps/snapshot/main.py::encode_file (query keys sorted, joined as
 * `__key-value`). */
export function staticFileUrl(path: string): string {
  const qIdx = path.indexOf("?");
  const pathname = (qIdx >= 0 ? path.slice(0, qIdx) : path).replace(/^\//, "");
  const params = new URLSearchParams(qIdx >= 0 ? path.slice(qIdx + 1) : "");
  const entries = [...params.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  const q = entries.map(([k, v]) => `${k}-${v}`).join("__");
  return `${BASE_PATH}/data/${pathname}${q ? `__${q}` : ""}.json`;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

const TIMEOUT_MS = 8000;
const MAX_GET_ATTEMPTS = 3;
// Transient gateway statuses the Next rewrite proxy returns while the API is
// mid-restart — retry these for GETs, then surface as a (recoverable) status-0.
const RETRY_STATUSES = new Set([502, 503, 504]);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Resilient fetch. GETs are idempotent, so they get a bounded retry with
 * backoff plus an 8s timeout; a connection failure or a transient gateway error
 * surfaces as `ApiError(0)` so the UI can auto-reconnect (see useApi). A real
 * HTTP error (4xx/5xx other than the gateway set) is deterministic and bubbles
 * immediately without retry. Non-GET methods are never retried.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();

  // Static-snapshot mode: serve GETs from baked JSON files; there is no live
  // server so writes (POST) have nothing to hit.
  if (STATIC_MODE) {
    if (method !== "GET") throw new ApiError(0, "static mode: no live server");
    const url = staticFileUrl(path);
    let resp: Response | null = null;
    for (let attempt = 1; attempt <= MAX_GET_ATTEMPTS; attempt++) {
      try {
        resp = await fetch(url, { cache: "no-store" });
      } catch {
        resp = null;
      }
      if (resp) {
        if (resp.ok) return (await resp.json()) as T;
        if (resp.status === 404) throw new ApiError(404, `Not found: ${url}`);
      }
      if (attempt < MAX_GET_ATTEMPTS) await sleep(400 * 2 ** (attempt - 1));
    }
    throw new ApiError(0, `Snapshot unreachable: ${url}`);
  }

  const maxAttempts = method === "GET" ? MAX_GET_ATTEMPTS : 1;
  const where = API_BASE_URL || "same-origin";
  let lastDetail = "";

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    let resp: Response | null = null;
    try {
      resp = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
        cache: "no-store",
        signal: ctrl.signal,
      });
    } catch (cause) {
      lastDetail = String(cause); // network error or 8s timeout (abort)
    } finally {
      clearTimeout(timer);
    }

    if (resp) {
      if (resp.ok) return (await resp.json()) as T;
      // Deterministic HTTP error (e.g. 400/404/500) -> bubble now, no retry.
      if (!(method === "GET" && RETRY_STATUSES.has(resp.status))) {
        const detail = await resp.text().catch(() => resp.statusText);
        throw new ApiError(resp.status, detail || resp.statusText);
      }
      lastDetail = `gateway ${resp.status}`; // transient proxy error -> retry
    }

    if (attempt < maxAttempts) await sleep(400 * 2 ** (attempt - 1)); // 400ms, 800ms
  }
  // Exhausted: treat as a (recoverable) connection failure.
  throw new ApiError(0, `API unreachable at ${where} (${lastDetail})`);
}

const v1 = "/api/v1";

export interface MarketCard {
  symbol: string; name: string; group: string; last: number | null;
  change_1d_pct: number | null; change_1w_pct: number | null;
  change_1m_pct: number | null; change_3m_pct: number | null;
  trend: string; status: string; source: string; as_of: string | null;
  is_proxy: boolean; interpretation_en: string; interpretation_ko: string;
}
export interface NarrativeBlock {
  key: string; label_en: string; label_ko: string;
  body_en: string; body_ko: string;
  bullets_en: string[]; bullets_ko: string[];
}
export interface RegimeNarrative {
  headline_en: string; headline_ko: string; blocks: NarrativeBlock[];
}
export interface RegimePulse {
  score: number; regime: string; regime_ko: string; regime_en: string;
  confidence: number; coverage: number; available: string[]; unavailable: string[];
  diagnosis_en: string; diagnosis_ko: string; narrative?: RegimeNarrative | null;
}
export interface MarketDriver {
  name: string; name_ko: string; direction: string; rank: number;
  confidence: number; evidence_en: string; evidence_ko: string;
}
export interface NextSession {
  session_date: string; open_et: string; open_kst: string;
  is_today: boolean; is_forecast: boolean;
  weekday_en: string; weekday_ko: string; label_en: string; label_ko: string;
}
export interface Overview {
  as_of: string; session: string; data_quality: string;
  pulse: RegimePulse; cards: MarketCard[]; drivers: MarketDriver[]; notes: string[];
  next_session?: NextSession | null;
}
export interface Metric {
  key: string; label_en: string; label_ko: string; value: number | null;
  unit: string; status: string; hint_en: string; hint_ko: string;
}
export interface IndexWatcher {
  market: string; name: string; as_of: string; cards: MarketCard[];
  metrics: Metric[]; diagnosis_en: string; diagnosis_ko: string; notes: string[];
}
export interface SectorRow {
  symbol: string; name: string; gics: string; ret_1w: number | null; ret_1m: number | null;
  ret_3m: number | null; ret_6m: number | null; rel_strength_1m: number | null;
  quadrant: string; status: string; as_of: string | null;
}
export interface StyleRow {
  style: string; symbol: string; name: string; ret_1m: number | null;
  rel_strength_1m: number | null; leading: boolean;
}
export interface Rotation {
  as_of: string; benchmark: string; sectors: SectorRow[]; style_leadership: StyleRow[];
  diagnosis_en: string; diagnosis_ko: string; notes: string[];
}

export const api = {
  health: () => request<Record<string, unknown>>("/health"),
  providersHealth: () => request<Record<string, unknown>>("/health/providers"),

  overview: () => request<Overview>(`${v1}/market/overview`),
  regime: () => request<RegimePulse>(`${v1}/market/regime`),
  crossAssets: () => request<{ as_of: string; cards: MarketCard[] }>(`${v1}/market/cross-assets`),

  index: (market: "sp500" | "nasdaq" | "dow" | "nyse") => request<IndexWatcher>(`${v1}/indices/${market}`),
  rotation: () => request<Rotation>(`${v1}/rotation`),
  macro: () => request<Record<string, any>>(`${v1}/macro`),

  recommendations: (q: { horizon?: string; action?: string; language?: string } = {}) => {
    // Drop undefined/empty so we never serialize `?horizon=undefined` (which the
    // API would treat as a literal filter and return nothing).
    const clean = Object.fromEntries(Object.entries(q).filter(([, v]) => v != null && v !== ""));
    const p = new URLSearchParams(clean as Record<string, string>).toString();
    return request<{ count: number; recommendations: any[]; empty_note: string | null }>(
      `${v1}/recommendations${p ? `?${p}` : ""}`,
    );
  },
  recommendationHistory: (ticker: string) =>
    request<{ ticker: string; history: any[] }>(`${v1}/recommendations/history/${ticker}`),
  // Weekly 🐋 대어 (Big-Bet) snapshot — frozen per ISO week.
  bigBets: () =>
    request<{ iso_week: string | null; as_of: string | null; picks: any[] }>(`${v1}/recommendations/big-bets`),

  news: (limit = 40) => request<{ count: number; clusters: any[]; empty_note: string | null }>(`${v1}/news?limit=${limit}`),

  briefingsLatest: (language = "en", type = "full") =>
    request<{ briefing: any | null; empty_note?: string }>(`${v1}/briefings/latest?language=${language}&briefing_type=${type}`),
  briefingsArchive: (language = "en") => request<{ archive: any[] }>(`${v1}/briefings/archive?language=${language}`),
  briefingByDate: (date: string, language = "en", type = "full") =>
    request<{ briefing: any }>(`${v1}/briefings/${date}?language=${language}&briefing_type=${type}`),

  agentsOrg: () => request<Record<string, any>>(`${v1}/agents/org`),
  agentRuns: () => request<{ runs: any[] }>(`${v1}/agents/runs`),
  run: (id: string) => request<Record<string, any>>(`${v1}/runs/${id}`),

  accuracy: () => request<Record<string, any>>(`${v1}/accuracy`),
  methodology: () => request<Record<string, any>>(`${v1}/methodology`),

  // Website-triggered analysis cycle (public, server-side cooldown). In static
  // mode there is no server to trigger — the snapshot auto-refreshes on a
  // schedule — so triggerRefresh just echoes the baked status.
  refreshStatus: () => request<RefreshStatus>(`${v1}/refresh/status`),
  triggerRefresh: () =>
    STATIC_MODE
      ? request<RefreshStatus>(`${v1}/refresh/status`).then((s) => ({ ...s, status: "static" as const }))
      : request<RefreshStatus & { status: string; retry_after_seconds?: number }>(
          `${v1}/refresh`, { method: "POST" },
        ),
};

export interface RefreshStatus {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  ok: boolean | null;
  detail: string;
  last_success_at: string | null;
  cooldown_remaining_seconds: number;
  llm: string;
}
