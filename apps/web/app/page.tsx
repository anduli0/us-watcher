"use client";

import { Activity, ChevronDown, Compass, Database, Eye, Info, RefreshCw } from "lucide-react";
import { useState } from "react";

import { ErrorNote, LeanBar, Loading, PageHeader, QualityBadge, StatusBadge, useApi } from "@/components/shell";
import { api, type MarketCard as Card, type NarrativeBlock, type NextSession, type RegimePulse } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn, fmtNum, fmtPct, pctClass, timeBoth } from "@/lib/utils";

function sessionLabel(session: string, lang: "en" | "ko"): string {
  if (lang !== "ko") return session;
  const m: Record<string, string> = {
    open: "장중", closed: "장 마감", premarket: "장 시작 전", afterhours: "시간외 거래",
    weekend: "주말 휴장", holiday: "휴장일",
  };
  return m[session] ?? session;
}

export default function OverviewPage() {
  const { t, lang, view } = useI18n();
  const ov = useApi(() => api.overview());

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("nav_overview")}
        subtitle={lang === "ko" ? "약 10초 안에 시장 상태를 파악하세요." : "Understand the market state in ~10 seconds."}
        right={ov.data && <button className="btn" onClick={ov.reload}><RefreshCw className="h-3.5 w-3.5" /> {t("refresh")}</button>}
      />

      {ov.loading && <Loading />}
      {ov.error && <ErrorNote error={ov.error} />}

      {ov.data && (
        <>
          {ov.data.next_session?.is_forecast && (
            <ForecastBanner ns={ov.data.next_session} session={ov.data.session} lang={lang} />
          )}
          <PulseHeader data={ov.data} />
          <MarketRead pulse={ov.data.pulse} />
          <section>
            <h2 className="section-label mb-3">{lang === "ko" ? "핵심 시장 카드" : "Core Market Cards"}</h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {ov.data.cards.map((c) => <MarketCardView key={c.symbol} c={c} lang={lang} pro={view === "pro"} />)}
            </div>
          </section>
          <Drivers data={ov.data} />
          {ov.data.notes.length > 0 && (
            <p className="text-xs text-muted">{ov.data.notes.join("  ·  ")}</p>
          )}
        </>
      )}
    </div>
  );
}

function ForecastBanner({ ns, session, lang }: { ns: NextSession; session: string; lang: "en" | "ko" }) {
  const label = lang === "ko" ? ns.label_ko : ns.label_en;
  const lead =
    lang === "ko"
      ? session === "weekend"
        ? "주말 휴장 — 다음 미국 장을 미리 전망합니다."
        : session === "holiday"
          ? "휴장일 — 다음 미국 장을 미리 전망합니다."
          : "장 마감 — 다음 미국 장을 미리 전망합니다."
      : session === "weekend"
        ? "Weekend close — here's the forecast for the next U.S. session."
        : session === "holiday"
          ? "Market holiday — here's the forecast for the next U.S. session."
          : "Market closed — here's the forecast for the next U.S. session.";
  return (
    <section className="card border-l-4 border-l-accent bg-accent/5">
      <div className="flex items-center gap-2 text-xs font-semibold text-accent">
        <Compass className="h-3.5 w-3.5" /> {lang === "ko" ? "다음 장 전망" : "Next-session forecast"}
      </div>
      <p className="mt-1 text-sm font-medium">{lead}</p>
      <p className="mt-1 num text-sm text-muted">{label}</p>
    </section>
  );
}

function PulseHeader({ data }: { data: NonNullable<ReturnType<typeof api.overview> extends Promise<infer T> ? T : never> }) {
  const { t, lang } = useI18n();
  const p = data.pulse;
  const regimeLabel = lang === "ko" ? p.regime_ko : p.regime_en;
  return (
    <section className="card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-[min(260px,100%)] flex-1">
          <div className="section-label">{t("regime")}</div>
          <div className="mt-1 text-3xl font-bold tracking-tight">{regimeLabel}</div>
          <div className="mt-3 max-w-2xl text-sm text-muted">
            {p.narrative ? (lang === "ko" ? p.narrative.headline_ko : p.narrative.headline_en) : (lang === "ko" ? p.diagnosis_ko : p.diagnosis_en)}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 text-right">
          <Stat label={t("composite")} value={`${p.score >= 0 ? "+" : ""}${p.score.toFixed(0)}`} sub="/ 100" tone={p.score > 9 ? "up" : p.score < -9 ? "down" : "muted"}
            hint={lang === "ko" ? "시장 국면 종합 점수 (−100~+100): +는 상승, −는 하락 우위. 0에서 멀수록 방향이 뚜렷합니다." : "Market-state score (−100…+100): + leans up, − leans down. Farther from 0 = clearer direction."} />
          <Stat label={t("confidence")} value={`${p.confidence.toFixed(0)}%`} sub={lang === "ko" ? `측정범위 ${(p.coverage * 100).toFixed(0)}%` : `cov ${(p.coverage * 100).toFixed(0)}%`}
            hint={lang === "ko" ? "신뢰도: 측정 범위와 신호 강도로 결정됩니다. 측정된 항목이 적을수록 낮아집니다." : "Confidence: from how much was measured and how strong the signal is. Lower when fewer components are measured."} />
        </div>
      </div>
      <div className="mt-4"><LeanBar value={p.score} /></div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="chip">{t("session")}: {sessionLabel(data.session, lang)}</span>
        <QualityBadge quality={data.data_quality} />
        <span className="chip">{t("updated")}: {timeBoth(data.as_of)}</span>
      </div>
    </section>
  );
}

const BLOCK_ICON: Record<string, typeof Info> = {
  summary: Info, drivers: Activity, stance: Compass, watch: Eye, coverage: Database,
};

function MarketRead({ pulse }: { pulse: RegimePulse }) {
  const { lang } = useI18n();
  const n = pulse.narrative;
  if (!n) return null;
  const find = (k: string) => n.blocks.find((b) => b.key === k);
  const summary = find("summary");
  const stance = find("stance");
  const drivers = find("drivers");
  const watch = find("watch");
  const coverage = find("coverage");
  return (
    <section className="card">
      <h2 className="section-label mb-2">{lang === "ko" ? "오늘의 시장 해석" : "Today's market read"}</h2>
      {summary && (
        <p className="max-w-3xl text-sm leading-relaxed text-foreground/90">
          {lang === "ko" ? summary.body_ko : summary.body_en}
        </p>
      )}
      {stance && (
        <div className="mt-4 rounded-lg border border-up/40 bg-up/5 p-3">
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold text-up">
            <Compass className="h-3.5 w-3.5" /> {lang === "ko" ? stance.label_ko : stance.label_en}
          </div>
          <p className="text-sm leading-relaxed">{lang === "ko" ? stance.body_ko : stance.body_en}</p>
        </div>
      )}
      <div className="mt-4 grid grid-cols-1 gap-5 md:grid-cols-2">
        {drivers && <Block block={drivers} lang={lang} />}
        {watch && <Block block={watch} lang={lang} />}
      </div>
      {coverage && (
        <div className="mt-4 flex items-start gap-2 border-t border-border pt-3 text-xs leading-relaxed text-muted">
          <Database className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{lang === "ko" ? coverage.body_ko : coverage.body_en}</span>
        </div>
      )}
    </section>
  );
}

function Block({ block, lang }: { block: NarrativeBlock; lang: "en" | "ko" }) {
  const Icon = BLOCK_ICON[block.key] ?? Info;
  const body = lang === "ko" ? block.body_ko : block.body_en;
  const bullets = lang === "ko" ? block.bullets_ko : block.bullets_en;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-muted">
        <Icon className="h-3.5 w-3.5" /> {lang === "ko" ? block.label_ko : block.label_en}
      </div>
      {body && <p className="text-sm leading-relaxed">{body}</p>}
      {bullets.length > 0 && (
        <ul className="space-y-1.5">
          {bullets.map((x, i) => (
            <li key={i} className="flex gap-2 text-sm leading-relaxed">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-foreground/40" />
              <span>{x}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Stat({ label, value, sub, tone = "foreground", hint }: { label: string; value: string; sub?: string; tone?: string; hint?: string }) {
  const toneCls = tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "muted" ? "text-muted" : "text-foreground";
  return (
    <div title={hint}>
      <div className="section-label">{label}</div>
      <div className={cn("num text-2xl font-bold", toneCls)}>{value}</div>
      {sub && <div className="num text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

function MarketCardView({ c, lang, pro }: { c: Card; lang: "en" | "ko"; pro: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="card card-hover">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold">{c.name}</div>
          <div className="num text-xl font-bold">{fmtNum(c.last)}</div>
        </div>
        <div className="text-right">
          <div className={cn("num text-sm font-semibold", pctClass(c.change_1d_pct))}>{fmtPct(c.change_1d_pct)}</div>
          {c.is_proxy && <span className="chip mt-1 text-warning">PROXY</span>}
        </div>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1 text-center text-[11px]">
        <Chg label="1W" v={c.change_1w_pct} />
        <Chg label="1M" v={c.change_1m_pct} />
        <Chg label="3M" v={c.change_3m_pct} />
      </div>
      <div className="mt-2 flex items-center justify-between">
        <StatusBadge status={c.status} />
        <button className="flex items-center gap-1 text-[11px] text-muted hover:text-foreground" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {t("why")} <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
        </button>
      </div>
      {open && <p className="mt-2 border-t border-border pt-2 text-xs text-muted">{lang === "ko" ? c.interpretation_ko : c.interpretation_en}</p>}
      {pro && c.as_of && <div className="mt-1 text-[10px] text-muted">{c.source} · {timeBoth(c.as_of)}</div>}
    </div>
  );
}

function Chg({ label, v }: { label: string; v: number | null }) {
  return (
    <div className="rounded bg-elevated/50 py-1">
      <div className="text-muted">{label}</div>
      <div className={cn("num font-medium", pctClass(v))}>{fmtPct(v, 1)}</div>
    </div>
  );
}

function Drivers({ data }: { data: Awaited<ReturnType<typeof api.overview>> }) {
  const { t, lang } = useI18n();
  if (!data.drivers.length) return null;
  return (
    <section className="card">
      <h2 className="section-label mb-3">{t("drivers")}</h2>
      <ul className="space-y-2">
        {data.drivers.map((d) => (
          <li key={d.name} className="flex items-center gap-3">
            <span className="num w-5 text-center text-sm font-bold text-muted">{d.rank}</span>
            <span className={cn("inline-flex w-20 justify-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
              d.direction === "supportive" ? "border-up/50 text-up" : d.direction === "headwind" ? "border-down/50 text-down" : "border-border text-muted")}>
              {d.direction}
            </span>
            <span className="text-sm font-medium">{lang === "ko" ? d.name_ko : d.name}</span>
            <span className="flex-1 text-right text-xs text-muted">{lang === "ko" ? d.evidence_ko : d.evidence_en}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
