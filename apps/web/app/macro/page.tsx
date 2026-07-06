"use client";

import { ErrorNote, Loading, PageHeader, StatusBadge, useApi } from "@/components/shell";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { fmtNum } from "@/lib/utils";

export default function MacroPage() {
  const { t, lang } = useI18n();
  const m = useApi(() => api.macro());

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav_macro")} subtitle={lang === "ko" ? "연준·금리·곡선·정책 전이 (비당파적)" : "Fed, rates, curve & policy transmission (nonpartisan)"} />
      {m.loading && <Loading />}
      {m.error && <ErrorNote error={m.error} />}
      {m.data && <MacroView data={m.data} lang={lang} />}
    </div>
  );
}

function MacroView({ data, lang }: { data: Record<string, any>; lang: "en" | "ko" }) {
  const chain: string[] = data.policy_transmission.chain;
  return (
    <>
      <section className="card">
        <h2 className="section-label mb-3">{lang === "ko" ? "매크로 스파인 (FRED)" : "Macro spine (FRED)"}</h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {data.series.map((s: any) => (
            <div key={s.series_id} className="flex flex-col gap-1">
              <span className="text-[11px] text-muted">{s.name}</span>
              <span className="num text-xl font-bold">{s.value == null ? "—" : `${fmtNum(s.value, 2)}%`}</span>
              <div className="flex items-center gap-1"><StatusBadge status={s.status} /></div>
              {s.observation_date && <span className="text-[10px] text-muted">{s.observation_date}</span>}
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h2 className="section-label mb-3">{lang === "ko" ? "정책 전이 체인" : "Policy transmission chain"}</h2>
        <ol className="flex flex-wrap items-center gap-2 text-xs">
          {chain.map((step, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="chip">{step}</span>
              {i < chain.length - 1 && <span className="text-muted">→</span>}
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-muted">{lang === "ko" ? data.policy_transmission.note_ko : data.policy_transmission.note_en}</p>
        <p className="mt-1 text-xs">
          {lang === "ko" ? "수익률곡선 상태" : "Yield-curve state"}: <span className="font-semibold">{data.policy_transmission.curve_state}</span>
        </p>
      </section>
    </>
  );
}
