import type { ActionStatus, Outcome } from "@/api/types";

const nf = new Intl.NumberFormat("en-US");
const cf = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export const num = (n: number | null | undefined) => (n === null || n === undefined ? "—" : nf.format(n));
export const compact = (n: number | null | undefined) => (n === null || n === undefined ? "—" : n < 10000 ? nf.format(n) : cf.format(n));
export const pct = (r: number | null | undefined, digits = 0) => (r === null || r === undefined ? "—" : `${(r * 100).toFixed(digits)}%`);

export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v < 1000) return `${Math.round(v)} ms`;
  return `${(v / 1000).toFixed(v < 10000 ? 1 : 0)} s`;
}

export function duration(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "—";
  if (s < 60) return `${Math.max(0, Math.round(s))}s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

// Backend timestamps are local server time without zone ("2026-11-23T20:44:49").
export const parseTs = (t: string) => new Date(t.length === 19 ? t : t.replace(" ", "T"));

export function dateTime(t: string | null | undefined): string {
  if (!t) return "—";
  return parseTs(t).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
export function timeOnly(t: string | null | undefined): string {
  if (!t) return "";
  return parseTs(t).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
export function dayLabel(d: string): string {
  return new Date(`${d}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
export function relative(t: string | null | undefined): string {
  if (!t) return "—";
  const diff = (Date.now() - parseTs(t).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`;
  return dateTime(t);
}

export const OUTCOMES: Record<Outcome, { label: string; tone: string }> = {
  action_completed: { label: "Action completed", tone: "good" },
  information_provided: { label: "Information provided", tone: "info" },
  escalated: { label: "Transferred to human", tone: "warning" },
  in_progress: { label: "In progress", tone: "accent" },
  unresolved: { label: "Unresolved", tone: "neutral" },
};

export const STATUSES: Record<ActionStatus, { label: string; tone: string }> = {
  succeeded: { label: "Successful", tone: "good" },
  pending: { label: "Pending", tone: "info" },
  failed: { label: "Failed", tone: "critical" },
  requires_human: { label: "Requires human", tone: "warning" },
};

export const ESCALATION_REASONS: Record<string, string> = {
  explicit_request: "Caller asked for a person",
  out_of_scope: "Out of scope (e.g. medical advice)",
  agent_requested: "Agent decided to transfer",
  unrecognised: "Request not understood",
  ambiguity: "Clarification failed",
  safety_positive: "Safety question answered yes",
  tool_error: "Action could not be executed",
  intent_escalate: "Topic handled by staff",
  audio_unusable: "Audio unusable",
};

export const escalationLabel = (r: string | null | undefined) => {
  if (!r) return "—";
  if (r.startsWith("signal:")) return `Signal detected (${r.slice(7)})`;
  return ESCALATION_REASONS[r] || humanize(r);
};

export function humanize(id: string | null | undefined): string {
  if (!id) return "—";
  const s = id.replace(/[_.]/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";

export function isoDay(d: Date): string {
  const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return z.toISOString().slice(0, 10);
}
export function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDay(d);
}
