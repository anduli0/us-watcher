"use client";

import { ErrorNote, Loading, PageHeader, useApi } from "@/components/shell";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function MethodologyPage() {
  const { t, lang } = useI18n();
  const acc = useApi(() => api.accuracy());
  const meth = useApi(() => api.methodology());

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav_methodology")} subtitle={lang === "ko" ? "추천 성과 추적 · 편향 방지 · 방법론" : "Recommendation tracking · bias prevention · methodology"} />

      <section className="card">
        <h2 className="section-label mb-3">{lang === "ko" ? "정확도 요약" : "Accuracy summary"}</h2>
        {acc.loading && <Loading />}
        {acc.error && <ErrorNote error={acc.error} />}
        {acc.data && (
          <div>
            <div className="flex flex-wrap gap-4 text-sm">
              <Stat label={lang === "ko" ? "평가 완료" : "Evaluated"} value={acc.data.evaluated_count} />
              <Stat label={lang === "ko" ? "대기 중" : "Pending"} value={acc.data.pending_count} />
            </div>
            {acc.data.note && <p className="mt-2 text-xs text-muted">{acc.data.note}</p>}
            {acc.data.backtest?.available && (
              <div className="mt-4">
                <div className="mb-2 flex items-center gap-2">
                  <h3 className="section-label">{lang === "ko" ? "신호 백테스트 (이력 검증)" : "Signal backtest (methodology validation)"}</h3>
                  {acc.data.backtest.calibration_monotonic && (
                    <span className="chip text-up">{lang === "ko" ? "캘리브레이션 단조↑" : "calibration monotonic"}</span>
                  )}
                  <span className="chip text-muted">{acc.data.backtest.universe_size} {lang === "ko" ? "종목" : "names"}</span>
                </div>
                <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-[11px] uppercase text-muted">
                    <th className="pb-1">{lang === "ko" ? "기간(일)" : "Horizon (d)"}</th>
                    <th className="pb-1 text-right">{lang === "ko" ? "롱신호" : "Long signals"}</th>
                    <th className="pb-1 text-right">{lang === "ko" ? "적중률" : "Hit rate"}</th>
                    <th className="pb-1 text-right">{lang === "ko" ? "평균수익" : "Avg ret"}</th>
                    <th className="pb-1 text-right">{lang === "ko" ? "초과수익" : "Excess"}</th>
                  </tr></thead>
                  <tbody>
                    {Object.entries(acc.data.backtest.by_horizon).map(([d, v]: [string, any]) => (
                      <tr key={d} className="border-t border-border/60">
                        <td className="num py-1">{d}</td>
                        <td className="num py-1 text-right">{v.long_signals}</td>
                        <td className="num py-1 text-right">{v.long_hit_rate != null ? `${(v.long_hit_rate * 100).toFixed(0)}%` : "—"}</td>
                        <td className="num py-1 text-right text-up">{v.long_avg_return_pct != null ? `${v.long_avg_return_pct}%` : "—"}</td>
                        <td className="num py-1 text-right">{v.long_avg_excess_pct != null ? `${v.long_avg_excess_pct}%` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
                <p className="mt-2 text-[11px] text-muted">{acc.data.backtest.note}</p>
              </div>
            )}
            {acc.data.by_horizon && Object.keys(acc.data.by_horizon).length > 0 && (
              <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-[11px] uppercase text-muted">
                  <th className="pb-1">Horizon (d)</th><th className="pb-1 text-right">N</th>
                  <th className="pb-1 text-right">Hit rate</th><th className="pb-1 text-right">Avg ret</th><th className="pb-1 text-right">Avg excess</th>
                </tr></thead>
                <tbody>
                  {Object.entries(acc.data.by_horizon).map(([d, v]: [string, any]) => (
                    <tr key={d} className="border-t border-border/60">
                      <td className="num py-1">{d}</td><td className="num py-1 text-right">{v.n}</td>
                      <td className="num py-1 text-right">{v.hit_rate ?? "—"}</td>
                      <td className="num py-1 text-right">{v.avg_return_pct ?? "—"}</td>
                      <td className="num py-1 text-right">{v.avg_excess_pct ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </div>
        )}
      </section>

      {meth.data && (
        <>
          <section className="card">
            <h2 className="section-label mb-2">{lang === "ko" ? "시장 국면 판정 엔진" : "Market state engine"}</h2>
            <p className="text-sm text-muted">{meth.data.regime_engine?.summary}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {meth.data.regime_engine?.bands?.map((b: any, i: number) => (
                <span key={i} className="chip"><span className="num">{b.range}</span> · {b.label}</span>
              ))}
            </div>
          </section>
          <section className="card">
            <h2 className="section-label mb-2">{lang === "ko" ? "편향 방지" : "Bias prevention"}</h2>
            <ul className="list-disc space-y-1 pl-4 text-sm text-muted">
              {meth.data.bias_prevention?.map((b: string, i: number) => <li key={i}>{b}</li>)}
            </ul>
          </section>
          <section className="card">
            <h2 className="section-label mb-2">{lang === "ko" ? "데이터 무결성" : "Data integrity"}</h2>
            <p className="text-sm text-muted">{meth.data.data_integrity?.principle}</p>
            <p className="mt-2 text-xs text-muted">{lang === "ko" ? "LLM이 절대 계산하지 않는 항목" : "LLM never computes"}: {(meth.data.data_integrity?.llm_never_computes ?? []).join(", ")}</p>
          </section>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-border px-4 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="num text-xl font-bold">{value}</div>
    </div>
  );
}
