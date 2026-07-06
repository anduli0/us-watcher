"use client";

import { useEffect, useRef, useState } from "react";

import { ErrorNote, Loading, PageHeader, useApi } from "@/components/shell";
import { API_BASE_URL, api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface LiveAgent { agent_id: string; direction: number; confidence: number; thesis: string }

function LiveCommittee() {
  const { lang } = useI18n();
  const [agents, setAgents] = useState<LiveAgent[]>([]);
  const [done, setDone] = useState<any>(null);
  const [streaming, setStreaming] = useState(false);
  const [failed, setFailed] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  const start = () => {
    setAgents([]); setDone(null); setFailed(false); setStreaming(true);
    const es = new EventSource(`${API_BASE_URL}/api/v1/agents/stream`);
    esRef.current = es;
    es.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "agent") setAgents((a) => [...a, msg]);
      else if (msg.type === "done") { setDone(msg); setStreaming(false); es.close(); }
      else if (msg.type === "empty") { setStreaming(false); es.close(); }
    };
    es.onerror = () => { setFailed(true); setStreaming(false); es.close(); };
  };
  useEffect(() => () => esRef.current?.close(), []);

  return (
    <section className="card">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="section-label">{lang === "ko" ? "라이브 위원회 피드 (SSE)" : "Live committee feed (SSE)"}</h2>
        <button className="btn" onClick={start} disabled={streaming}>
          {streaming ? (lang === "ko" ? "스트리밍…" : "streaming…") : (lang === "ko" ? "▶ 최근 심의 재생" : "▶ Replay latest")}
        </button>
      </div>
      {failed && <p className="text-xs text-warning">{lang === "ko" ? "스트림 불가(프록시 버퍼링) — 아래 정적 실행 목록을 사용하세요." : "Stream unavailable (proxy buffering) — see the static runs below (polling fallback)."}</p>}
      {agents.length > 0 && (
        <ul className="space-y-1">
          {agents.map((a, i) => (
            <li key={i} className="flex items-center gap-2 text-xs">
              <span className={cn("inline-flex w-14 justify-center rounded border px-1 py-0.5 num",
                a.direction > 0.05 ? "border-up/50 text-up" : a.direction < -0.05 ? "border-down/50 text-down" : "border-border text-muted")}>
                {a.direction >= 0 ? "+" : ""}{a.direction.toFixed(2)}
              </span>
              <span className="font-medium">{a.agent_id}</span>
              <span className="text-muted">· {a.confidence.toFixed(0)}%</span>
              <span className="flex-1 truncate text-muted">{a.thesis}</span>
            </li>
          ))}
        </ul>
      )}
      {done?.aggregate && (
        <div className="mt-3 rounded-lg bg-elevated/50 p-2 text-xs">
          <span className="font-semibold">{lang === "ko" ? "종합" : "Aggregate"}: </span>
          {done.aggregate.label} · dir {done.aggregate.direction} · conf {done.aggregate.confidence}%
          {done.chief?.narrative_en && <p className="mt-1 text-muted">{lang === "ko" ? done.chief.narrative_ko : done.chief.narrative_en}</p>}
        </div>
      )}
      {agents.length === 0 && !streaming && !failed && (
        <p className="text-xs text-muted">{lang === "ko" ? "최근 오케스트레이터 심의를 에이전트별로 재생합니다." : "Replays the latest orchestrator deliberation agent-by-agent."}</p>
      )}
    </section>
  );
}

export default function AgentsPage() {
  const { t, lang } = useI18n();
  const org = useApi(() => api.agentsOrg());
  const runs = useApi(() => api.agentRuns());

  return (
    <div className="space-y-6">
      <PageHeader title={t("nav_agents")} subtitle={lang === "ko" ? "23개 전문가 풀 + 3개 감독 계층 · 이벤트별 동적 활성화" : "23-specialist pool + 3 supervisory roles · dynamically activated per event"} />
      <LiveCommittee />

      {org.loading && <Loading />}
      {org.error && <ErrorNote error={org.error} />}
      {org.data && (
        <>
          <section className="card">
            <h2 className="section-label mb-3">{lang === "ko" ? "감독 계층" : "Supervisory layer"}</h2>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {org.data.supervisory.map((a: any) => (
                <div key={a.id} className="rounded-lg border border-accent/30 bg-accent/5 p-3">
                  <div className="text-sm font-semibold">{a.name}</div>
                  <div className="mt-1 text-[11px] text-muted">{a.scope}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="section-label">{lang === "ko" ? "전문가 데스크" : "Specialist desks"} ({org.data.specialist_count})</h2>
            {org.data.desks.map((d: any) => (
              <div key={d.id} className="card">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{d.name}</h3>
                  <span className="chip">weight {d.weight}</span>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {d.agents.map((a: any) => (
                    <div key={a.id} className="rounded-lg border border-border p-2">
                      <div className="text-xs font-medium">{a.name}</div>
                      <div className="mt-0.5 text-[10px] text-muted">{a.scope}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </section>
        </>
      )}

      <section className="card">
        <h2 className="section-label mb-3">{lang === "ko" ? "최근 오케스트레이터 실행" : "Recent orchestrator runs"}</h2>
        {runs.loading && <Loading />}
        {runs.data && runs.data.runs.length === 0 && <p className="text-sm text-muted">{lang === "ko" ? "아직 실행 없음. /orchestrator/run 으로 실행하세요." : "No runs yet. Trigger via /orchestrator/run."}</p>}
        {runs.data && runs.data.runs.length > 0 && (
          <div className="space-y-2">
            {runs.data.runs.map((r: any) => (
              <div key={r.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-border p-3 text-xs">
                <span className={cn("chip", r.status === "completed" ? "text-up" : "text-warning")}>{r.status}</span>
                <span className="font-medium">{r.objective}</span>
                <span className="text-muted">{r.runtime}</span>
                <span className="text-muted">{(r.selected_agents ?? []).length} agents</span>
                <span className="num text-muted">{r.token_usage} tok</span>
                <span className="ml-auto text-muted">{r.started_at}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
