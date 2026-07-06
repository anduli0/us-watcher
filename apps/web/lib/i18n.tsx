"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type Lang = "en" | "ko";
export type ViewMode = "simple" | "pro";

type Dict = Record<string, { en: string; ko: string }>;

// UI chrome strings. Analytical content (diagnoses, theses) arrives from the API
// already in both languages, so this dictionary covers navigation/labels only.
export const T: Dict = {
  brand_sub: { en: "U.S. Equity Market Intelligence", ko: "미국 주식시장 AI 인텔리전스" },
  nav_overview: { en: "U.S. Overview", ko: "미국 개요" },
  nav_sp500: { en: "S&P 500", ko: "S&P 500" },
  nav_nasdaq: { en: "Nasdaq", ko: "나스닥" },
  nav_dow: { en: "Dow Jones", ko: "다우존스" },
  nav_nyse: { en: "NYSE", ko: "NYSE" },
  nav_rotation: { en: "Sector & Rotation", ko: "섹터·로테이션" },
  nav_macro: { en: "Macro & Policy", ko: "매크로·정책" },
  nav_reco: { en: "AI Recommendations", ko: "AI 추천" },
  nav_news: { en: "News Scrapbook", ko: "뉴스 스크랩북" },
  nav_brief: { en: "Daily Brief", ko: "데일리 브리핑" },
  nav_methodology: { en: "Accuracy & Methodology", ko: "정확도·방법론" },
  nav_agents: { en: "Agents", ko: "에이전트" },
  refresh_now: { en: "Update now", ko: "지금 업데이트" },
  refresh_running: { en: "Analyzing…", ko: "분석 중…" },
  refresh_cooldown: { en: "Recently updated", ko: "방금 업데이트됨" },
  refresh_failed: { en: "Update failed — try later", ko: "업데이트 실패 — 잠시 후 다시" },
  refresh_last: { en: "Updated", ko: "업데이트" },
  refresh_auto: { en: "Auto-updated", ko: "자동 갱신" },
  refresh_auto_hint: {
    en: "This site is a cloud snapshot that refreshes automatically on a schedule — it stays online even when the owner's computer is off.",
    ko: "이 사이트는 정해진 시각에 자동으로 갱신되는 클라우드 스냅샷입니다. 운영자 컴퓨터가 꺼져 있어도 계속 열립니다.",
  },
  loading: { en: "Loading…", ko: "불러오는 중…" },
  reconnecting: { en: "Reconnecting to the server…", ko: "서버에 다시 연결하는 중…" },
  reconnecting_hint: {
    en: "This is automatic — the page refreshes itself in a moment.",
    ko: "자동으로 다시 시도하고 있어요. 잠시 후 화면이 알아서 갱신됩니다.",
  },
  request_failed: { en: "Couldn't load this data", ko: "데이터를 불러오지 못했습니다" },
  regime: { en: "Market State", ko: "시장 국면" },
  hot: { en: "Hot", ko: "HOT" },
  composite: { en: "Composite score", ko: "종합 점수" },
  confidence: { en: "Confidence", ko: "신뢰도" },
  drivers: { en: "Market Drivers", ko: "시장 동인" },
  diagnosis: { en: "Diagnosis", ko: "진단" },
  why: { en: "Why?", ko: "왜?" },
  updated: { en: "Updated", ko: "갱신" },
  session: { en: "Session", ko: "세션" },
  data_quality: { en: "Data quality", ko: "데이터 품질" },
  refresh: { en: "Refresh", ko: "새로고침" },
  metrics: { en: "Metrics", ko: "지표" },
  no_data: { en: "No data yet.", ko: "데이터가 아직 없습니다." },
  evidence: { en: "Evidence", ko: "근거" },
  risks: { en: "Risks", ko: "리스크" },
  catalysts: { en: "Catalysts", ko: "상승 계기" },
  invalidation: { en: "Invalidation", ko: "투자판단 무효 조건" },
  dissent: { en: "Dissenting view", ko: "반대 의견" },
  scenarios: { en: "Scenarios", ko: "시나리오" },
  horizon: { en: "Horizon", ko: "투자기간" },
  action: { en: "Action", ko: "투자 판단" },
  score: { en: "Score", ko: "점수" },
  brief_archive: { en: "Past briefs", ko: "지난 브리프" },
  brief_latest: { en: "Latest", ko: "최신" },
  brief_viewing_past: { en: "Viewing an archived brief", ko: "지난 브리프를 보는 중" },
  brief_back_latest: { en: "Back to latest", ko: "최신으로" },
  brief_auto_note: {
    en: "Auto-generated daily and archived — open any past date below.",
    ko: "매일 자동 생성·보관됩니다 — 아래에서 지난 날짜를 열어볼 수 있어요.",
  },
};

interface I18nState {
  lang: Lang;
  view: ViewMode;
  setLang: (l: Lang) => void;
  setView: (v: ViewMode) => void;
  t: (key: keyof typeof T | string) => string;
}

const Ctx = createContext<I18nState | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    const l = (localStorage.getItem("usw.lang") as Lang) || "en";
    setLangState(l);
  }, []);

  const setLang = (l: Lang) => { setLangState(l); localStorage.setItem("usw.lang", l); };
  const t = (key: string) => (T[key] ? T[key][lang] : key);

  // The Simple/Professional toggle was removed (it added little); the richer
  // ("pro") details — metric hints, data provenance — now always show.
  return <Ctx.Provider value={{ lang, view: "pro", setLang, setView: () => {}, t }}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nState {
  const c = useContext(Ctx);
  if (!c) throw new Error("useI18n must be used within I18nProvider");
  return c;
}

/** Pick the language-appropriate field from an API object exposing _en/_ko. */
export function pick(obj: Record<string, unknown>, base: string, lang: Lang): string {
  const v = obj[`${base}_${lang}`] ?? obj[`${base}_en`] ?? "";
  return typeof v === "string" ? v : "";
}
