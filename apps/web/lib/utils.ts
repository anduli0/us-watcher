import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Format a signed percent with color class (US: up=green, down=red). */
export function pctClass(v: number | null | undefined): string {
  if (v == null) return "text-muted";
  return v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted";
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function timeBoth(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const et = d.toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const kst = d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" });
  return `${et} ET · ${kst} KST`;
}
