"use client";

import { Download, FileText, History, LayoutList, Printer, RotateCcw } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorNote, Loading, PageHeader, useApi } from "@/components/shell";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn, timeBoth } from "@/lib/utils";

type Selection = { date: string; type: string } | null;

const TYPE_LABEL: Record<string, { en: string; ko: string }> = {
  full: { en: "Full", ko: "종합" },
  premarket: { en: "Pre-market", ko: "장전" },
  midday: { en: "Midday", ko: "장중" },
  closing: { en: "Closing", ko: "마감" },
};

export default function BriefPage() {
  const { t, lang } = useI18n();
  const [view, setView] = useState<"report" | "sections">("report");
  // null selection = show the most recent FULL brief; otherwise an archived one.
  const [sel, setSel] = useState<Selection>(null);

  const b = useApi(
    () => (sel ? api.briefingByDate(sel.date, lang, sel.type) : api.briefingsLatest(lang, "full")),
    [lang, sel?.date ?? "latest", sel?.type ?? "full"],
  );
  const archive = useApi(() => api.briefingsArchive(lang), [lang]);

  return (
    <div className="space-y-6">
      <div className="no-print">
        <PageHeader
          title={t("nav_brief")}
          subtitle={lang === "ko"
            ? "전 섹션을 엮은 종합 보고서 · 매일 자동 생성·보관 · 인쇄/PDF·다운로드 제출용"
            : "All sections woven into one report · auto-generated & archived daily · print/PDF & download"}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_260px]">
        <div className="space-y-4">
          {sel && (
            <div className="no-print flex items-center justify-between rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-xs">
              <span className="text-accent">{t("brief_viewing_past")}: {sel.date} · {(TYPE_LABEL[sel.type]?.[lang]) ?? sel.type}</span>
              <button className="flex items-center gap-1 font-medium text-accent hover:underline" onClick={() => setSel(null)}>
                <RotateCcw className="h-3 w-3" /> {t("brief_back_latest")}
              </button>
            </div>
          )}
          {b.loading && <Loading />}
          {b.error && <ErrorNote error={b.error} />}
          {b.notFound && <EmptyState note={t("no_data")} />}
          {b.data && !b.data.briefing && <EmptyState note={(b.data as { empty_note?: string }).empty_note ?? t("no_data")} />}
          {b.data?.briefing && (
            <>
              <Toolbar view={view} setView={setView} brief={b.data.briefing} lang={lang} />
              {view === "report"
                ? <ReportDoc md={b.data.briefing.payload?.report_md ?? ""} by={b.data.briefing.payload?.report_generated_by} lang={lang} />
                : <SectionView brief={b.data.briefing} lang={lang} />}
            </>
          )}
        </div>

        <Archive
          items={archive.data?.archive ?? []}
          loading={archive.loading}
          lang={lang}
          t={t}
          sel={sel}
          onSelect={setSel}
        />
      </div>
    </div>
  );
}

function Archive({ items, loading, lang, t, sel, onSelect }: {
  items: { briefing_date: string; briefing_type: string; headline: string }[];
  loading: boolean;
  lang: "en" | "ko";
  t: (k: string) => string;
  sel: Selection;
  onSelect: (s: Selection) => void;
}) {
  const isActive = (it: { briefing_date: string; briefing_type: string }) =>
    sel === null ? false : sel.date === it.briefing_date && sel.type === it.briefing_type;
  return (
    <aside className="no-print lg:sticky lg:top-24 lg:self-start">
      <div className="card">
        <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <History className="h-4 w-4 text-accent" /> {t("brief_archive")}
        </h2>
        <p className="mb-3 text-[11px] leading-relaxed text-muted">{t("brief_auto_note")}</p>
        <button
          onClick={() => onSelect(null)}
          className={cn("mb-2 w-full rounded-md border px-2.5 py-1.5 text-left text-xs font-medium transition-colors",
            sel === null ? "border-accent/50 bg-accent/15 text-accent" : "border-border text-muted hover:bg-elevated/50")}
        >
          {t("brief_latest")} · {(TYPE_LABEL.full?.[lang]) ?? "Full"}
        </button>
        {loading && <p className="text-xs text-muted">{t("loading")}</p>}
        {!loading && items.length === 0 && <p className="text-xs text-muted">{t("no_data")}</p>}
        <ul className="max-h-[60vh] space-y-1 overflow-y-auto pr-1">
          {items.map((it) => (
            <li key={`${it.briefing_date}-${it.briefing_type}`}>
              <button
                onClick={() => onSelect({ date: it.briefing_date, type: it.briefing_type })}
                title={it.headline}
                className={cn("w-full rounded-md px-2.5 py-1.5 text-left text-xs transition-colors",
                  isActive(it) ? "bg-accent/15 text-accent" : "text-muted hover:bg-elevated/50 hover:text-foreground")}
              >
                <span className="font-mono">{it.briefing_date}</span>
                <span className="ml-1.5 rounded bg-elevated px-1 py-0.5 text-[10px] uppercase tracking-wide">
                  {(TYPE_LABEL[it.briefing_type]?.[lang]) ?? it.briefing_type}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}

function Toolbar({ view, setView, brief, lang }: { view: string; setView: (v: "report" | "sections") => void; brief: any; lang: "en" | "ko" }) {
  const md: string = brief.payload?.report_md ?? "";
  const download = () => {
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `usw-brief-${brief.briefing_date}-${lang}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="no-print flex flex-wrap items-center gap-2">
      <div className="flex overflow-hidden rounded-lg border border-border text-xs">
        <button onClick={() => setView("report")} className={cn("flex items-center gap-1 px-3 py-1.5", view === "report" ? "bg-accent/20 text-accent" : "text-muted")}>
          <FileText className="h-3.5 w-3.5" /> {lang === "ko" ? "종합 보고서" : "Report"}
        </button>
        <button onClick={() => setView("sections")} className={cn("flex items-center gap-1 px-3 py-1.5", view === "sections" ? "bg-accent/20 text-accent" : "text-muted")}>
          <LayoutList className="h-3.5 w-3.5" /> {lang === "ko" ? "섹션 보기" : "Sections"}
        </button>
      </div>
      <button className="btn" onClick={() => window.print()}><Printer className="h-3.5 w-3.5" /> {lang === "ko" ? "인쇄 / PDF" : "Print / PDF"}</button>
      <button className="btn" onClick={download}><Download className="h-3.5 w-3.5" /> Markdown</button>
    </div>
  );
}

/** Minimal, dependency-free Markdown renderer for the report document. */
function ReportDoc({ md, by, lang }: { md: string; by?: string; lang: "en" | "ko" }) {
  if (!md) return <EmptyState note={lang === "ko" ? "보고서가 아직 생성되지 않았습니다." : "Report not generated yet."} />;
  return (
    <article className="report-doc card mx-auto max-w-3xl">
      {by && (
        <div className="no-print mb-3 text-[11px] text-muted">
          {lang === "ko" ? "생성" : "Generated"}: {by === "llm" ? (lang === "ko" ? "LLM 합성 (수치는 결정론적)" : "LLM-synthesized (numbers deterministic)") : (lang === "ko" ? "결정론적" : "deterministic")}
        </div>
      )}
      <Markdown text={md} />
    </article>
  );
}

function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(<ul key={`u${blocks.length}`} className="my-2 list-disc space-y-1 pl-5 text-sm text-muted">{list.map((it, i) => <li key={i}><Inline t={it} /></li>)}</ul>);
      list = [];
    }
  };
  lines.forEach((raw, i) => {
    const line = raw.trimEnd();
    if (line.startsWith("- ")) { list.push(line.slice(2)); return; }
    flush();
    if (!line.trim()) return;
    if (line.startsWith("# ")) blocks.push(<h1 key={i} className="mb-1 text-2xl font-bold tracking-tight">{line.slice(2)}</h1>);
    else if (line.startsWith("## ")) blocks.push(<h2 key={i} className="mb-1 mt-5 border-b border-border pb-1 text-sm font-semibold uppercase tracking-[0.12em] text-accent">{line.slice(3)}</h2>);
    else if (line.startsWith("> ")) blocks.push(<blockquote key={i} className="my-2 border-l-2 border-accent/60 pl-3 text-base font-semibold">{<Inline t={line.slice(2)} />}</blockquote>);
    else if (line.startsWith("---")) blocks.push(<hr key={i} className="my-4 border-border" />);
    else blocks.push(<p key={i} className="my-1.5 text-sm leading-relaxed"><Inline t={line} /></p>);
  });
  flush();
  return <div>{blocks}</div>;
}

/** Inline **bold** and _italic_. */
function Inline({ t }: { t: string }) {
  const parts = t.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("**") && p.endsWith("**")) return <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>;
        if (p.startsWith("_") && p.endsWith("_")) return <em key={i} className="text-muted">{p.slice(1, -1)}</em>;
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}

function SectionView({ brief, lang }: { brief: any; lang: "en" | "ko" }) {
  const p = brief.payload;
  return (
    <article className="space-y-5">
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="chip">{brief.briefing_date} · {brief.briefing_type.toUpperCase()}</span>
          <span className="text-[11px] text-muted">{lang === "ko" ? "데이터 시각" : "Data time"}: {timeBoth(p.data_timestamp)} · {p.data_quality}</span>
        </div>
        <h2 className="mt-3 text-xl font-bold">{brief.headline}</h2>
        <p className="mt-2 text-sm text-muted">{p.executive_summary}</p>
      </section>
      {p.what_changed?.items && (
        <section className="card border-accent/30">
          <h3 className="section-label mb-2 text-accent">{lang === "ko" ? "어제 대비 변화" : "What Changed Since Yesterday"}</h3>
          <ul className="list-disc space-y-1 pl-4 text-sm">{p.what_changed.items.map((it: string, i: number) => <li key={i}>{it}</li>)}</ul>
        </section>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {p.sections?.map((s: any, i: number) => (
          <section key={i} className="card">
            <h3 className="section-label mb-2">{s.title}</h3>
            <p className="text-sm leading-relaxed text-muted">{s.body}</p>
          </section>
        ))}
      </div>
      <section className="card text-xs text-muted">
        <div className="font-semibold text-foreground">{lang === "ko" ? "출처 & 고지" : "Sources & disclaimer"}</div>
        <div className="mt-1">{(p.sources ?? []).join(" · ")}</div>
        <p className="mt-2">{p.disclaimer}</p>
      </section>
    </article>
  );
}
