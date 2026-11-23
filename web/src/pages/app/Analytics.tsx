import { useState } from "react";
import { Link } from "react-router-dom";
import { Info } from "lucide-react";
import { api, qs } from "@/api/client";
import type { Analytics } from "@/api/types";
import { HourColumns, RankedBars, StackedColumns, TrendChart } from "@/components/charts";
import { Badge, ErrorState, PageHeader, Skeleton, Stat } from "@/components/ui";
import { useAgents } from "@/lib/agents";
import { compact, daysAgo, duration, escalationLabel, isoDay, ms, num, OUTCOMES, pct } from "@/lib/format";
import { useAsync, useDocumentTitle } from "@/lib/hooks";

const PRESETS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "mtd", label: "Month to date" },
];

export function AnalyticsPage() {
  useDocumentTitle("Analytics");
  const { agents } = useAgents();
  const [range, setRange] = useState("30");
  const [agentId, setAgentId] = useState("");
  const from = range === "mtd" ? `${isoDay(new Date()).slice(0, 8)}01` : daysAgo(Number(range) - 1);
  const { data: a, error, loading, reload } = useAsync((s) => api.get<Analytics>(`/analytics${qs({ from, agent_id: agentId })}`, s), [from, agentId]);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  const t = a?.totals;
  const daily = (a?.daily || []) as unknown as Record<string, unknown>[];

  return (
    <>
      <PageHeader title="Analytics" sub="Performance, cost and efficiency of your agents, computed from recorded conversations." />
      <div className="toolbar">
        <select className="select select-sm" style={{ width: "auto" }} value={range} onChange={(e) => setRange(e.target.value)} aria-label="Date range">
          {PRESETS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        <select className="select select-sm" style={{ width: "auto" }} value={agentId} onChange={(e) => setAgentId(e.target.value)} aria-label="Agent">
          <option value="">All agents</option>
          {agents.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
        {loading && <span className="spinner subtle" />}
      </div>

      {!a || !t ? (
        <Skeleton h={600} />
      ) : (
        <div className="stack gap-4" style={{ opacity: loading ? 0.6 : 1 }}>
          <h2 className="section-title" style={{ marginTop: 0 }}>Conversations</h2>
          <div className="stat-row">
            <Stat label="Conversations" value={num(t.conversations)} sub={`${num(t.voice_conversations)} voice · ${num(t.chat_conversations)} chat`} />
            <Stat label="Average duration" value={duration(t.avg_duration_s)} sub={`${num(t.turns)} turns in total`} />
            <Stat label="Resolution rate" value={pct(t.resolution_rate)} sub="action completed or question answered" />
            <Stat label="Handled without a human" value={pct(t.automation_rate)} sub={`${num(t.handled_without_human)} conversations`} />
          </div>
          <div className="grid-2">
            <StackedColumns title="Conversations per day" sub="By channel" data={daily} series={[{ key: "chat", label: "Chat", slot: 1 }, { key: "voice", label: "Voice", slot: 2 }]} />
            <HourColumns title="Peak activity" sub="Conversations started, by hour of day" rows={a.hours} />
          </div>
          <div className="grid-2">
            <RankedBars title="Outcomes" rows={a.outcomes.map((o) => ({ label: OUTCOMES[o.outcome]?.label || o.outcome, value: o.count }))} slot={3} />
            <RankedBars title="Transfer reasons" sub="Why conversations reached a human" rows={a.escalation_reasons.map((r) => ({ label: escalationLabel(r.reason), value: r.count }))} empty="No conversation was transferred in this period." slot={2} />
          </div>

          <h2 className="section-title">AI performance</h2>
          <div className="stat-row">
            <Stat label="Avg response latency" value={ms(t.avg_latency_ms)} sub={`chat ${ms(t.avg_latency_chat_ms)} · voice ${ms(t.avg_latency_voice_ms)}`} />
            <Stat label="Intent recognised" value={pct(t.understood_rate)} sub="turns the model understood" />
            <Stat label="Action success rate" value={pct(t.action_success_rate)} sub={`${num(t.actions_succeeded)} ok · ${num(t.actions_failed)} failed`} />
            <Stat label="Escalation rate" value={pct(t.escalation_rate)} sub={`${num(t.escalations)} transferred`} />
          </div>
          <div className="grid-2">
            <TrendChart title="Response latency" sub={`Average per day · p50 ${ms(t.p50_latency_ms)} · p90 ${ms(t.p90_latency_ms)}`} data={daily} series={[{ key: "avg_latency_ms", label: "Avg latency", slot: 1 }]} fmt={(v) => ms(v)} />
            <RankedBars title="Actions by type" rows={a.action_types.map((x) => ({ label: x.label, value: x.count, hint: `${x.succeeded} successful` }))} empty="No action in this period." />
          </div>
          <div className="stat-row">
            <Stat label="Turns handled by the LLM" value={pct(t.llm_usage_rate)} sub={`${num(t.llm_turns)} of ${num(t.turns)}`} />
            <Stat label="LLM unavailable" value={num(t.llm_failed_turns)} sub="turns that fell back to rules" />
            <Stat label="Avg action duration" value={ms(t.avg_action_duration_ms)} sub="tool execution time" />
            <Stat label="Awaiting / needs human" value={`${num(t.actions_pending)} / ${num(t.actions_requires_human)}`} sub="pending · requires human" />
          </div>

          <h2 className="section-title">Usage</h2>
          <div className="stat-row">
            <Stat label="LLM tokens" value={compact(t.total_tokens)} sub={`${compact(t.prompt_tokens)} in · ${compact(t.completion_tokens)} out`} />
            <Stat label="LLM calls" value={num(t.llm_calls)} />
            <Stat label="ElevenLabs characters" value={num(t.tts_chars)} sub="billed characters (cache hits are free)" />
            <Stat label="Speech-to-text audio" value={`${t.stt_seconds.toFixed(0)} s`} sub="transcribed locally" />
          </div>
          <div className="grid-2">
            <TrendChart title="Token consumption" sub="LLM tokens per day" data={daily} series={[{ key: "tokens", label: "Tokens", slot: 1 }]} />
            <TrendChart title="Voice synthesis" sub="ElevenLabs characters per day" data={daily} series={[{ key: "tts_chars", label: "Characters", slot: 2 }]} />
          </div>
          <div className="card card-pad row-between wrap">
            <div className="row gap-3">
              <Info size={18} className="subtle" />
              <div>
                <div className="strong">Estimated API cost</div>
                {a.estimated_cost ? (
                  <div className="small muted">
                    LLM {a.estimated_cost.llm.toFixed(4)} + voice {a.estimated_cost.tts.toFixed(4)} = <b>{a.estimated_cost.total.toFixed(4)} {a.estimated_cost.currency}</b>, based on the unit prices you entered.
                  </div>
                ) : (
                  <div className="small muted">Not computed: enter your providers' unit prices in Settings to estimate costs. Free tiers cost nothing.</div>
                )}
              </div>
            </div>
            {a.estimated_cost ? <Badge tone="outline">Estimate</Badge> : <Link to="/app/settings#usage" className="btn btn-secondary btn-sm">Set prices</Link>}
          </div>
        </div>
      )}
    </>
  );
}
