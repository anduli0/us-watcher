"use client";

import { ErrorNote, Loading, PageHeader, StatusBadge, useApi } from "@/components/shell";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn, fmtNum, fmtPct, pctClass, timeBoth } from "@/lib/utils";

type Market = "sp500" | "nasdaq" | "dow" | "nyse";

export function IndexWatcherView({ market }: { market: Market }) {
  const { lang, view } = useI18n();
  const w = useApi(() => api.index(market), [market]);

  return (
    <div className="space-y-6">
      {w.loading && <Loading />}
      {w.error && <ErrorNote error={w.error} />}
      {w.data && (
        <>
          <PageHeader title={w.data.name} subtitle={timeBoth(w.data.as_of)} />
          <section className="card">
            <h2 className="section-label mb-2">{lang === "ko" ? "진단" : "Diagnosis"}</h2>
            <p className="text-sm leading-relaxed">{lang === "ko" ? w.data.diagnosis_ko : w.data.diagnosis_en}</p>
          </section>

          <section>
            <h2 className="section-label mb-3">{lang === "ko" ? "구성 지표·ETF" : "Index & ETFs"}</h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {w.data.cards.map((c) => (
                <div key={c.symbol} className="card">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="text-sm font-semibold">{c.name}</div>
                      <div className="num text-lg font-bold">{fmtNum(c.last)}</div>
                    </div>
                    <div className={cn("num text-sm font-semibold", pctClass(c.change_1d_pct))}>{fmtPct(c.change_1d_pct)}</div>
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[11px] text-muted">
                    <span>1M <span className={cn("num", pctClass(c.change_1m_pct))}>{fmtPct(c.change_1m_pct, 1)}</span></span>
                    <StatusBadge status={c.status} />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <h2 className="section-label mb-3">{lang === "ko" ? "정량 지표" : "Quantitative metrics"}</h2>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
              {w.data.metrics.map((m) => (
                <div key={m.key} className="flex flex-col">
                  <span className="text-[11px] text-muted">{lang === "ko" ? m.label_ko : m.label_en}</span>
                  <span className="num text-base font-semibold">
                    {m.value == null ? "—" : `${m.value}${m.unit}`}
                  </span>
                  {view === "pro" && (lang === "ko" ? m.hint_ko : m.hint_en) && (
                    <span className="text-[10px] text-muted">{lang === "ko" ? m.hint_ko : m.hint_en}</span>
                  )}
                </div>
              ))}
            </div>
          </section>

          {w.data.notes.length > 0 && <p className="text-xs text-muted">{w.data.notes.join("  ·  ")}</p>}
        </>
      )}
    </div>
  );
}
