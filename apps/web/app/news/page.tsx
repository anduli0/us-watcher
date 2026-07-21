"use client";

import { EmptyState, ErrorNote, Loading, PageHeader, useApi } from "@/components/shell";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn, timeBoth } from "@/lib/utils";

export default function NewsPage() {
  const { t, lang } = useI18n();
  const n = useApi(() => api.news(60));

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav_news")} subtitle={lang === "ko" ? "이벤트 클러스터링 · 중요도 점수 · 원문 링크" : "Event-clustered · importance-scored · linked to source"} />
      {n.loading && <Loading />}
      {n.error && <ErrorNote error={n.error} />}
      {n.data && n.data.count === 0 && <EmptyState note={n.data.empty_note ?? t("no_data")} />}
      {n.data && n.data.count > 0 && (
        <div className="space-y-3">
          {n.data.clusters.map((c: any) => (
            <article key={c.id} className="card card-hover">
              <div className="flex items-start gap-3">
                <ImportanceBadge value={c.importance} />
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-semibold leading-snug">{c.headline}</h3>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted">
                    <span>{timeBoth(c.last_seen)}</span>
                    {c.article_count > 1 && <span className="chip">{c.article_count} {lang === "ko" ? "기사" : "sources"}</span>}
                    {(c.related?.indices ?? []).map((x: string) => <span key={x} className="chip text-accent">{x}</span>)}
                    {(c.related?.sectors ?? []).map((x: string) => <span key={x} className="chip">{x}</span>)}
                    {(c.related?.macro ?? []).map((x: string) => <span key={x} className="chip text-warning">{x}</span>)}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function ImportanceBadge({ value }: { value: number }) {
  const tone = value >= 60 ? "border-danger/50 text-danger" : value >= 45 ? "border-warning/50 text-warning" : "border-border text-muted";
  return (
    <div className={cn("grid h-11 w-11 shrink-0 place-items-center rounded-lg border", tone)}>
      <span className="num text-sm font-bold">{value.toFixed(0)}</span>
    </div>
  );
}
