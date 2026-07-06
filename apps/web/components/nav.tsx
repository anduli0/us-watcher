"use client";

import {
  Activity, BarChart3, Bot, FileText, Gauge, Globe, Landmark, LineChart,
  Newspaper, Building2, Layers, RefreshCw, Target, type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, STATIC_MODE, type RefreshStatus } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// Ordered by how the owner actually consumes the site: decision surfaces first
// (overview -> picks -> brief -> news), context next (rotation/macro), raw
// index detail after, meta (accuracy/agents) last.
const NAV: { href: string; key: string; Icon: LucideIcon }[] = [
  { href: "/", key: "nav_overview", Icon: Globe },
  { href: "/recommendations", key: "nav_reco", Icon: Target },
  { href: "/brief", key: "nav_brief", Icon: FileText },
  { href: "/news", key: "nav_news", Icon: Newspaper },
  { href: "/rotation", key: "nav_rotation", Icon: Layers },
  { href: "/macro", key: "nav_macro", Icon: Landmark },
  { href: "/sp500", key: "nav_sp500", Icon: LineChart },
  { href: "/nasdaq", key: "nav_nasdaq", Icon: Activity },
  { href: "/dow", key: "nav_dow", Icon: Building2 },
  { href: "/nyse", key: "nav_nyse", Icon: BarChart3 },
  { href: "/methodology", key: "nav_methodology", Icon: Gauge },
  { href: "/agents", key: "nav_agents", Icon: Bot },
];

/** Static-mode indicator: the site is a CDN snapshot that auto-refreshes on a
 * schedule (independent of any computer being on), so there is nothing to
 * trigger — just show when it was last updated. */
function StaticUpdatedChip() {
  const { t, lang } = useI18n();
  const [at, setAt] = useState<string | null>(null);
  useEffect(() => {
    api.refreshStatus().then((s) => setAt(s.last_success_at)).catch(() => {});
  }, []);
  const label = at
    ? new Date(at).toLocaleString(lang === "ko" ? "ko-KR" : "en-US",
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "";
  return (
    <span
      title={t("refresh_auto_hint")}
      className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs font-medium text-muted"
    >
      <RefreshCw className="h-3.5 w-3.5" aria-hidden />
      <span className="whitespace-nowrap">{t("refresh_auto")}{label ? ` · ${label}` : ""}</span>
    </span>
  );
}

/** "Update now" — kicks the server-side analysis cycle (works from any phone
 * browser; the heavy lifting and the LLM run on the server). Polls status while
 * a run is in flight, then reloads the page so fresh numbers/prose appear. */
function RefreshButton() {
  const { t, lang } = useI18n();
  const [st, setSt] = useState<RefreshStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const wasRunning = useRef(false);
  const running = st?.running ?? false;
  const cooling = !running && (st?.cooldown_remaining_seconds ?? 0) > 0;

  const poll = useCallback(async () => {
    try {
      const s = await api.refreshStatus();
      if (wasRunning.current && !s.running) window.location.reload();
      wasRunning.current = s.running;
      setSt(s);
      if (s.ok === false) setFailed(true);
    } catch { /* status is cosmetic — never break the nav */ }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(() => {
      if (wasRunning.current) poll();
    }, 5000);
    return () => clearInterval(id);
  }, [poll]);

  const onClick = async () => {
    if (running || cooling) return;
    setFailed(false);
    try {
      const r = await api.triggerRefresh();
      wasRunning.current = r.status === "started" || r.status === "running";
      setSt(r);
    } catch { setFailed(true); }
  };

  const label = running ? t("refresh_running")
    : failed ? t("refresh_failed")
    : cooling ? t("refresh_cooldown")
    : t("refresh_now");
  const lastAt = st?.last_success_at
    ? new Date(st.last_success_at).toLocaleTimeString(lang === "ko" ? "ko-KR" : "en-US",
        { hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <button
      onClick={onClick}
      disabled={running || cooling}
      title={lastAt ? `${t("refresh_last")} ${lastAt}` : undefined}
      className={cn(
        "flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs font-medium transition-colors",
        running ? "text-accent" : cooling ? "text-muted" : "text-foreground hover:bg-elevated",
      )}
    >
      <RefreshCw className={cn("h-3.5 w-3.5", running && "animate-spin")} aria-hidden />
      <span className="whitespace-nowrap">{label}</span>
    </button>
  );
}

export function NavBar() {
  const path = usePathname();
  const { t, lang, setLang } = useI18n();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
        <Link href="/" className="flex items-center gap-2 shrink-0">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/15 text-accent font-bold">US</span>
          <div className="leading-tight">
            <div className="text-sm font-bold tracking-tight">US Stock Watcher</div>
            <div className="text-[10px] text-muted">{t("brand_sub")}</div>
          </div>
        </Link>
        <div className="flex items-center gap-2">
          {STATIC_MODE ? <StaticUpdatedChip /> : <RefreshButton />}
          <div className="flex overflow-hidden rounded-lg border border-border text-xs font-medium">
            <button onClick={() => setLang("en")} className={cn("px-2.5 py-1", lang === "en" ? "bg-accent/20 text-accent" : "text-muted")}>EN</button>
            <button onClick={() => setLang("ko")} className={cn("px-2.5 py-1", lang === "ko" ? "bg-accent/20 text-accent" : "text-muted")}>한</button>
          </div>
        </div>
      </div>
      <nav className="mx-auto max-w-7xl overflow-x-auto px-2 pb-1" aria-label="Primary">
        <ul className="flex gap-1">
          {NAV.map(({ href, key, Icon }) => (
            <li key={href}>
              <Link
                href={href}
                aria-current={active(href) ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition-colors",
                  active(href) ? "bg-elevated text-foreground" : "text-muted hover:text-foreground hover:bg-elevated/50",
                )}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden /> {t(key)}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}

export function SiteFooter() {
  const { lang } = useI18n();
  return (
    <footer className="mt-16 border-t border-border bg-surface/50">
      <div className="mx-auto max-w-7xl space-y-4 px-4 py-8 text-xs text-muted">
        <p className="leading-relaxed">
          {lang === "ko"
            ? "US Stock Watcher가 제공하는 시장 분석, 시나리오, 점수 및 종목·ETF 관련 판단은 정보 제공과 연구·교육을 목적으로 한 AI 기반 분석 결과입니다. 이는 맞춤형 투자자문이나 매수·매도 권유가 아닙니다. 데이터는 지연·오류가 있을 수 있으며, 과거의 성과는 미래 수익을 보장하지 않습니다."
            : "Market analysis, scenarios, scores, and stock/ETF assessments from US Stock Watcher are AI-generated for informational, research, and educational purposes only — not personalized investment advice or a solicitation to buy or sell any security. Data may be delayed or inaccurate; past performance does not guarantee future results."}
        </p>
        <div className="rounded-lg border border-border bg-background/60 p-4 font-mono text-[11px] leading-relaxed text-muted">
          <div className="font-semibold text-foreground">US Stock Watcher — United States Equity Market Intelligence</div>
          <div>Designed, owned, and operated by Minkyu An · 안민규</div>
          <div>© 2026 Minkyu An. All rights reserved.</div>
          <div className="mt-1">Unauthorized reproduction or commercial redistribution of the proprietary analytical framework, agent orchestration, scoring models, report formats, and original UI is prohibited.</div>
          <div className="mt-1 text-accent">ID-2026-MA-USW-01</div>
          <div className="mt-2 text-muted">Excludes third-party market data, news articles, public government data, open-source libraries, and exchange/index-provider trademarks & methodologies.</div>
        </div>
      </div>
    </footer>
  );
}
