"use client";

import { ErrorNote, Loading, PageHeader, QuadrantBadge, useApi } from "@/components/shell";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn, fmtPct, pctClass, timeBoth } from "@/lib/utils";

export default function RotationPage() {
  const { t, lang } = useI18n();
  const r = useApi(() => api.rotation());

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav_rotation")} subtitle={r.data ? `${t("updated")}: ${timeBoth(r.data.as_of)} · vs ${r.data.benchmark}` : undefined} />
      {r.loading && <Loading />}
      {r.error && <ErrorNote error={r.error} />}
      {r.data && (
        <>
          <section className="card">
            <h2 className="section-label mb-2">{lang === "ko" ? "무엇이 바뀌었나" : "What changed"}</h2>
            <p className="text-sm">{lang === "ko" ? r.data.diagnosis_ko : r.data.diagnosis_en}</p>
          </section>

          <section className="card overflow-x-auto">
            <h2 className="section-label mb-3">{lang === "ko" ? "섹터 상대강도" : "Sector relative strength"}</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase text-muted">
                  <th className="pb-2">{lang === "ko" ? "섹터" : "Sector"}</th>
                  <th className="pb-2 text-right">1W</th><th className="pb-2 text-right">1M</th>
                  <th className="pb-2 text-right">3M</th><th className="pb-2 text-right">6M</th>
                  <th className="pb-2 text-right">RS 1M</th><th className="pb-2 text-right">{lang === "ko" ? "사분면" : "Quadrant"}</th>
                </tr>
              </thead>
              <tbody>
                {r.data.sectors.map((s) => (
                  <tr key={s.symbol} className="border-t border-border/60">
                    <td className="py-2"><span className="font-medium">{s.name}</span> <span className="text-[11px] text-muted">{s.symbol}</span></td>
                    <td className={cn("num py-2 text-right", pctClass(s.ret_1w))}>{fmtPct(s.ret_1w, 1)}</td>
                    <td className={cn("num py-2 text-right", pctClass(s.ret_1m))}>{fmtPct(s.ret_1m, 1)}</td>
                    <td className={cn("num py-2 text-right", pctClass(s.ret_3m))}>{fmtPct(s.ret_3m, 1)}</td>
                    <td className={cn("num py-2 text-right", pctClass(s.ret_6m))}>{fmtPct(s.ret_6m, 1)}</td>
                    <td className={cn("num py-2 text-right font-semibold", pctClass(s.rel_strength_1m))}>{fmtPct(s.rel_strength_1m, 1)}</td>
                    <td className="py-2 text-right"><QuadrantBadge q={s.quadrant} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2 className="section-label mb-3">{lang === "ko" ? "스타일 리더십" : "Style leadership"}</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              {r.data.style_leadership.map((s) => (
                <div key={s.symbol} className={cn("rounded-lg border p-3 text-center", s.leading ? "border-up/40 bg-up/5" : "border-border")}>
                  <div className="text-xs font-semibold">{s.style}</div>
                  <div className={cn("num mt-1 text-sm font-bold", pctClass(s.rel_strength_1m))}>{fmtPct(s.rel_strength_1m, 1)}</div>
                  <div className="text-[10px] text-muted">{s.symbol}</div>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
