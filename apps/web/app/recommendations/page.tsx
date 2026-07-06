"use client";

import { useMemo, useState } from "react";

import { ActionBadge, EmptyState, ErrorNote, Loading, PageHeader, useApi } from "@/components/shell";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const FILTERS = [
  { k: "hot", en: "🔥 HOT", ko: "🔥 HOT" },
  { k: "short", en: "Short", ko: "단기" },
  { k: "medium", en: "Medium", ko: "중기" },
  { k: "medium_long", en: "Med-Long", ko: "중장기" },
];
const HOT_TOP_N = 8;
const MOONSHOT_TOP_N = 6;

export default function RecommendationsPage() {
  const { t, lang } = useI18n();
  const [filter, setFilter] = useState("hot");
  const isHot = filter === "hot";
  const r = useApi(() => api.recommendations(isHot ? {} : { horizon: filter }), [filter]);
  const bigBets = useApi(() => api.bigBets(), []); // weekly 🐋 대어 snapshot (frozen per ISO week)

  const recs = useMemo<any[]>(() => {
    if (!r.data) return [];
    if (isHot) {
      // The hottest names by attention (analyst coverage + revisions + momentum +
      // flows), one row per ticker (its strongest-conviction call).
      const best = new Map<string, any>();
      for (const rec of r.data.recommendations) {
        const cur = best.get(rec.ticker);
        if (!cur || (rec.hotness_score ?? 0) > (cur.hotness_score ?? 0)) best.set(rec.ticker, rec);
      }
      return [...best.values()]
        .sort((a, b) => (b.hotness_score ?? 0) - (a.hotness_score ?? 0))
        .slice(0, HOT_TOP_N);
    }
    return [...r.data.recommendations].sort((a, b) => b.total_score - a.total_score);
  }, [r.data, isHot]);

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav_reco")} subtitle={lang === "ko" ? "증거 기반 · 신뢰도·리스크·무효화 조건 명시" : "Evidence-based · with confidence, risks & invalidation"} />

      <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-warning">
        {lang === "ko"
          ? "AI 분석 결과이며 투자자문이 아닙니다. 데이터는 지연·오류가 있을 수 있습니다."
          : "AI-generated analysis, not investment advice. Data may be delayed or inaccurate."}
      </div>

      <MoonshotSection snapshot={bigBets.data} lang={lang} />

      <ScoreLegend lang={lang} />

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((h) => (
          <button key={h.k} onClick={() => setFilter(h.k)}
            className={cn("rounded-lg border px-3 py-1.5 text-xs font-medium", filter === h.k ? "border-accent/60 bg-accent/15 text-accent" : "border-border text-muted")}>
            {lang === "ko" ? h.ko : h.en}
          </button>
        ))}
      </div>

      {isHot && (
        <p className="text-xs text-muted">
          {lang === "ko"
            ? `뉴스·애널리스트·증권사 관심(애널리스트 수·실적 추정치 변경·최근 모멘텀·자금유입)이 가장 높은 종목 TOP ${HOT_TOP_N}.`
            : `Top ${HOT_TOP_N} names drawing the most attention — analyst coverage, estimate revisions, recent momentum, and inflows.`}
        </p>
      )}

      {r.loading && <Loading />}
      {r.error && <ErrorNote error={r.error} />}
      {r.data && recs.length === 0 && <EmptyState note={r.data.empty_note ?? t("no_data")} />}
      {recs.length > 0 && (
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
          {recs.map((rec: any) => <RecoCard key={`${rec.ticker}:${rec.horizon}`} rec={rec} lang={lang} showHot={isHot} />)}
        </div>
      )}
    </div>
  );
}

function MoonshotSection({ snapshot, lang }: { snapshot: any; lang: "en" | "ko" }) {
  const top = useMemo<any[]>(
    () => (snapshot?.picks ?? [])
      .filter((rec: any) => (rec.moonshot_score ?? 0) > 0)
      .slice(0, MOONSHOT_TOP_N),
    [snapshot],
  );
  if (top.length === 0) return null;
  const updated = snapshot?.as_of ? new Date(snapshot.as_of).toLocaleDateString(lang === "ko" ? "ko-KR" : "en-US") : null;
  return (
    <section className="rounded-xl border border-accent2/40 bg-gradient-to-br from-accent2/10 to-transparent p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-base">🐋</span>
        <h2 className="text-sm font-bold">{lang === "ko" ? "대어 — 지금은 저평가, 미래는 폭발적" : "Big Bets — cheap now, explosive upside"}</h2>
        {updated && (
          <span className="chip border-accent2/40 text-accent2" title={lang === "ko" ? "대어는 매주 한 번 갱신됩니다" : "Big Bets refresh once per week"}>
            {lang === "ko" ? `주간 갱신 · ${updated}` : `Weekly · ${updated}`}
          </span>
        )}
      </div>
      <p className="mt-1 text-xs leading-relaxed text-muted">
        {lang === "ko"
          ? "기술적 수급이 아니라, 미래 성장 잠재력이 폭발적이면서 아직 가격이 눌려 있는 종목들을 과감하게 골랐습니다. 2017년의 엔비디아, 2025년의 샌디스크처럼 '터지기 전' 종목을 노립니다. 매주 한 번 갱신되며(종목은 주마다 겹칠 수 있음), 변동성이 크고 확신 구간이 넓은 고위험·고수익 베팅입니다."
          : "Not technicals — bold bets where future-growth potential looks explosive while the price is still depressed. Aiming for the kind of name NVIDIA was in 2017 or SanDisk in 2025. Refreshed once a week (names may repeat week to week); high-risk, high-reward with wide uncertainty."}
      </p>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {top.map((rec) => <MoonshotCard key={rec.ticker} rec={rec} lang={lang} />)}
      </div>
    </section>
  );
}

function MoonshotCard({ rec, lang }: { rec: any; lang: "en" | "ko" }) {
  const hasTarget = rec.target_low != null && rec.target_high != null;
  const theme = lang === "ko" ? rec.spotlight_theme_ko : rec.spotlight_theme_en;
  const note = lang === "ko" ? rec.spotlight_note_ko : rec.spotlight_note_en;
  return (
    <div className="rounded-lg border border-border bg-background/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-base font-bold">{rec.ticker}</span>
        <span className="chip border-accent2/50 text-accent2" title={lang === "ko" ? "대어 점수: 성장 잠재력 × 저평가(모멘텀 제외)" : "Big-bet score: growth potential × cheapness (excludes momentum)"}>🐋 {Math.round(rec.moonshot_score)}</span>
      </div>
      <div className="text-xs text-muted">{rec.company_name}</div>
      {theme && (
        <div className="mt-1.5 inline-flex items-center gap-1 rounded border border-accent2/40 bg-accent2/10 px-1.5 py-0.5 text-[10px] font-medium text-accent2">🔭 {theme}</div>
      )}
      <p className="mt-2 text-xs leading-relaxed">{note || (lang === "ko" ? rec.rationale_ko : rec.rationale_en)}</p>
      {hasTarget && (
        <div className="mt-2 border-t border-border pt-2 text-[11px]" title={lang === "ko" ? rec.target_basis_ko : rec.target_basis_en}>
          <span className="section-label">{lang === "ko" ? "목표 밴드" : "Target"}</span>{" "}
          <span className="num font-semibold">${rec.target_low}–${rec.target_high}</span>{" "}
          <span className="text-muted">({horizonLabel(rec.horizon, lang)})</span>
        </div>
      )}
    </div>
  );
}

function pick(rec: any, base: string, lang: "en" | "ko"): string {
  return (lang === "ko" ? rec[`${base}_ko`] : rec[`${base}_en`]) || rec[`${base}_en`] || rec[base] || "";
}
function pickList(rec: any, base: string, lang: "en" | "ko"): string[] {
  const ko = rec[`${base}_ko`];
  if (lang === "ko" && Array.isArray(ko) && ko.length) return ko;
  return rec[base] ?? [];
}

function RecoCard({ rec, lang, showHot }: { rec: any; lang: "en" | "ko"; showHot?: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const rationale = lang === "ko" ? rec.rationale_ko : rec.rationale_en;
  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-bold">{rec.ticker}</span>
            <ActionBadge action={rec.action} lang={lang} />
            <span className="chip">{horizonLabel(rec.horizon, lang)}</span>
            {showHot && rec.hotness_score != null && (
              <span className="chip border-danger/40 text-danger" title={lang === "ko" ? "관심도" : "Attention score"}>🔥 {Math.round(rec.hotness_score)}</span>
            )}
            {(lang === "ko" ? rec.spotlight_theme_ko : rec.spotlight_theme_en) && (
              <span className="chip border-accent2/40 text-accent2" title={lang === "ko" ? "관심 테마 (하우스 스포트라이트)" : "Focus theme (house spotlight)"}>🔭 {lang === "ko" ? rec.spotlight_theme_ko : rec.spotlight_theme_en}</span>
            )}
            {rec.capital_migration_score != null && (
              <span className="chip text-accent2" title="Capital Migration Score">CMS {Math.round(rec.capital_migration_score)}</span>
            )}
          </div>
          <div className="mt-0.5 text-xs text-muted">{rec.company_name} · {assetLabel(rec.asset_type, lang)}</div>
        </div>
        <div className="text-right">
          <div className="num text-xl font-bold" title={lang === "ko" ? "종합 점수 (0~100): 여러 요인을 가중 합산한 매력도. 높을수록 매수 쪽." : "Composite score (0–100): weighted attractiveness. Higher leans buy."}>{rec.total_score?.toFixed?.(0) ?? rec.total_score}</div>
          <div className="num text-[11px] text-muted" title={lang === "ko" ? "신뢰도: 그 점수를 얼마나 믿을 수 있는지(데이터 품질·신호 일치도)." : "Confidence: how much to trust the score (data quality + signal agreement)."}>{t("confidence")} {rec.confidence?.toFixed?.(0) ?? rec.confidence}%</div>
        </div>
      </div>
      <p className="mt-2 text-sm">{lang === "ko" ? rec.one_line_thesis_ko : rec.one_line_thesis_en}</p>

      {rec.target_low != null && rec.target_high != null && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs" title={lang === "ko" ? rec.target_basis_ko : rec.target_basis_en}>
          <span className="section-label">🎯 {lang === "ko" ? "목표 밴드" : "Target"}</span>
          <span className="num font-semibold">${rec.target_low} ~ ${rec.target_high}</span>
          <span className="text-muted">({horizonLabel(rec.horizon, lang)})</span>
        </div>
      )}

      <button className="mt-3 text-xs text-accent hover:underline" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? (lang === "ko" ? "접기" : "Hide details") : (lang === "ko" ? "근거·시나리오 보기" : "Evidence & scenarios")}
      </button>

      {open && (
        <div className="mt-3 space-y-3 border-t border-border pt-3 text-xs">
          {rationale && (
            <div className="rounded-lg border border-accent/30 bg-accent/5 p-2.5 text-[13px] leading-relaxed text-foreground/90">
              {rationale}
            </div>
          )}
          {(lang === "ko" ? rec.target_basis_ko : rec.target_basis_en) && (
            <div className="text-[11px] leading-relaxed text-muted">
              <span className="section-label">🎯 {lang === "ko" ? "목표가 산출 근거" : "How the target is derived"}</span>{" "}
              {lang === "ko" ? rec.target_basis_ko : rec.target_basis_en}
            </div>
          )}
          {(pick(rec, "fundamental_summary", lang) || pick(rec, "valuation_summary", lang)) && (
            <div className="space-y-1 rounded-lg bg-elevated/40 p-2">
              {pick(rec, "fundamental_summary", lang) && (
                <div><span className="section-label">{lang === "ko" ? "펀더멘털" : "Fundamentals"}</span>{" "}
                  <span className="text-muted">{pick(rec, "fundamental_summary", lang)}</span></div>
              )}
              <div><span className="section-label">{lang === "ko" ? "밸류에이션" : "Valuation"}</span>{" "}
                <span className="text-muted">{pick(rec, "valuation_summary", lang)}</span></div>
              {pick(rec, "capital_migration_summary", lang) && (
                <div><span className="section-label text-accent2">{lang === "ko" ? "자본이동(CMS)" : "Capital Migration"}{rec.capital_migration_score != null ? ` ${Math.round(rec.capital_migration_score)}/100` : ""}</span>{" "}
                  <span className="text-muted">{pick(rec, "capital_migration_summary", lang)}</span></div>
              )}
            </div>
          )}
          <List title={t("evidence")} items={pickList(rec, "reasons", lang)} />
          <List title={t("catalysts")} items={pickList(rec, "catalysts", lang)} />
          <List title={t("risks")} items={pickList(rec, "risks", lang)} tone="down" />
          <List title={t("invalidation")} items={pickList(rec, "invalidation_conditions", lang)} tone="warning" />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {["bull_scenario", "base_scenario", "bear_scenario"].map((k) => {
              const sc = rec[k];
              if (!sc) return null;
              return (
                <div key={k} className="rounded-lg border border-border p-2">
                  <div className="font-semibold">{scenarioLabel(sc.label, lang)} · {(sc.probability * 100).toFixed(0)}%</div>
                  <div className="mt-1 leading-relaxed text-muted">{lang === "ko" ? sc.narrative_ko : sc.narrative_en}</div>
                </div>
              );
            })}
          </div>
          <div className="rounded-lg bg-elevated/50 p-2 leading-relaxed">
            <span className="font-semibold">{t("dissent")}: </span>{pick(rec, "dissent_summary", lang)}
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreLegend({ lang }: { lang: "en" | "ko" }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-lg border border-border bg-elevated/30 p-3 text-xs leading-relaxed text-muted sm:grid-cols-2">
      <div>
        <span className="section-label">{lang === "ko" ? "점수 (0~100)" : "Score (0–100)"}</span>{" "}
        {lang === "ko"
          ? "기술적 흐름·펀더멘털·밸류에이션·실적·섹터 등을 투자기간별 가중치로 합산한 종합 매력도입니다. 높을수록 매수, 낮을수록 매도 쪽이며 점수 구간이 곧 판단이 됩니다(80↑ 적극매수 · 68~79 매수 · 45~57 보유 · 22↓ 회피)."
          : "A weighted composite of technical, fundamental, valuation, earnings and sector factors (weights vary by horizon). Higher leans buy, lower leans sell; the band sets the call (80+ strong buy · 68–79 buy · 45–57 hold · under 22 avoid)."}
      </div>
      <div>
        <span className="section-label">{lang === "ko" ? "신뢰도" : "Confidence"}</span>{" "}
        {lang === "ko"
          ? "그 점수를 얼마나 믿을 수 있는지입니다. 데이터 품질·측정 범위와 여러 신호의 일치도가 높을수록 올라갑니다. 낮을 때는 방향만 참고하고 비중은 작게 가져가는 편이 안전합니다."
          : "How much to trust that score — it rises with data quality/coverage and how well the signals agree. When it's low, treat the direction as a tilt and size positions smaller."}
      </div>
    </div>
  );
}

function List({ title, items, tone }: { title: string; items?: string[]; tone?: string }) {
  if (!items || !items.length) return null;
  const toneCls = tone === "down" ? "text-down" : tone === "warning" ? "text-warning" : "text-foreground";
  return (
    <div>
      <div className={cn("section-label", toneCls)}>{title}</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 leading-relaxed text-muted">
        {items.map((it, i) => <li key={i}>{it}</li>)}
      </ul>
    </div>
  );
}

function horizonLabel(h: string, lang: "en" | "ko"): string {
  if (lang !== "ko") return h;
  return { short: "단기", medium: "중기", medium_long: "중장기" }[h] ?? h;
}
function assetLabel(a: string, lang: "en" | "ko"): string {
  if (lang !== "ko") return a;
  return { stock: "주식", etf: "ETF", covered_call_etf: "커버드콜 ETF" }[a] ?? a;
}
function scenarioLabel(s: string, lang: "en" | "ko"): string {
  if (lang !== "ko") return s.charAt(0).toUpperCase() + s.slice(1);
  return { bull: "상승", base: "기본", bear: "하락" }[s] ?? s;
}
