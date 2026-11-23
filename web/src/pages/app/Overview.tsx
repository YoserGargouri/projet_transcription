import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle, ArrowRight, Bot, BookOpen, Clock, Coins, MessageSquareText, Mic, Timer, UserRoundCheck, Workflow, Zap,
} from "lucide-react";
import { api } from "@/api/client";
import type { ActionRow, ConversationRow, Dashboard } from "@/api/types";
import { RankedBars, StackedColumns, TrendChart } from "@/components/charts";
import { Badge, Card, CardHeader, EmptyState, ErrorState, OutcomeBadge, PageHeader, Skeleton, Stat, StatusBadge } from "@/components/ui";
import { useAgents } from "@/lib/agents";
import { useAuth } from "@/lib/auth";
import { compact, duration, escalationLabel, humanize, ms, num, OUTCOMES, pct, relative } from "@/lib/format";
import { useAsync, useDocumentTitle } from "@/lib/hooks";

export function Overview() {
  useDocumentTitle("Overview");
  const { me } = useAuth();
  const { agents, loading: agentsLoading } = useAgents();
  const { data, error, loading, reload } = useAsync((s) => api.get<Dashboard>("/dashboard?days=14", s), []);
  const first = me?.user.name.split(" ")[0];

  if (error) return <ErrorState error={error} onRetry={reload} />;
  const a = data?.analytics;
  const t = a?.totals;
  const empty = t && t.conversations === 0;

  return (
    <>
      <PageHeader
        title={first ? `Welcome back, ${first}` : "Overview"}
        sub={<>Activity of your agents over the last 14 days. Every number is computed from conversations recorded in this workspace.</>}
        actions={
          <>
            <Badge tone="good"><span className="dot" />Live workspace data</Badge>
            <Link to="/app/playground" className="btn btn-primary btn-sm">
              <Zap /> Open Playground
            </Link>
          </>
        }
      />

      {!agentsLoading && agents.length === 0 && <Onboarding />}
      {agents.length > 0 && empty && (
        <Card className="card-pad" >
          <div className="row-between wrap">
            <div className="row gap-3">
              <div className="empty-icon" style={{ margin: 0 }}><MessageSquareText /></div>
              <div>
                <div className="strong">No conversations in this period yet</div>
                <div className="small muted">Talk to your agent in the Playground: each conversation, action and model call will appear here.</div>
              </div>
            </div>
            <Link to="/app/playground" className="btn btn-secondary btn-sm">Start a conversation <ArrowRight /></Link>
          </div>
        </Card>
      )}

      <div className="stack gap-4" style={{ marginTop: agents.length === 0 || empty ? 16 : 0 }}>
        {loading && !data ? (
          <Skeleton h={190} />
        ) : t ? (
          <>
            <div className="stat-row">
              <Stat icon={<MessageSquareText />} label="Total conversations" value={num(t.conversations)} sub={`${num(t.turns)} turns`} />
              <Stat icon={<Mic />} label="Voice conversations" value={num(t.voice_conversations)} sub={`${num(t.chat_conversations)} by chat`} />
              <Stat icon={<UserRoundCheck />} label="Handled without a human" value={pct(t.automation_rate)} sub={`${num(t.escalations)} transferred`} />
              <Stat icon={<Workflow />} label="Actions executed" value={num(t.actions_succeeded)} sub={t.actions_failed ? `${t.actions_failed} failed` : `${num(t.actions_pending)} awaiting confirmation`} />
            </div>
            <div className="stat-row">
              <Stat icon={<Clock />} label="Avg conversation duration" value={duration(t.avg_duration_s)} />
              <Stat icon={<Timer />} label="Avg response time" value={ms(t.avg_latency_ms)} sub={t.p90_latency_ms ? `p90 ${ms(t.p90_latency_ms)}` : "per agent turn"} />
              <Stat icon={<Coins />} label="LLM tokens" value={compact(t.total_tokens)} sub={`${num(t.llm_calls)} model calls`} />
              <Stat icon={<Bot />} label="Resolution rate" value={pct(t.resolution_rate)} sub="action completed or question answered" />
            </div>
          </>
        ) : null}

        {a && (
          <>
            <div className="grid-2">
              <StackedColumns
                title="Conversations over time"
                sub="Chat versus voice, per day"
                data={a.daily as unknown as Record<string, unknown>[]}
                series={[{ key: "chat", label: "Chat", slot: 1 }, { key: "voice", label: "Voice", slot: 2 }]}
              />
              <TrendChart
                title="Actions executed over time"
                sub="Operations run by the agent, per day"
                data={a.daily as unknown as Record<string, unknown>[]}
                series={[{ key: "actions_succeeded", label: "Successful", slot: 1 }, { key: "actions_failed", label: "Failed", slot: 2 }]}
              />
            </div>
            <div className="grid-3">
              <RankedBars title="Customer requests" sub="Intent of each turn" rows={a.intents.map((i) => ({ label: humanize(i.intent), value: i.count }))} />
              <RankedBars title="Conversation outcomes" rows={a.outcomes.map((o) => ({ label: OUTCOMES[o.outcome]?.label || o.outcome, value: o.count }))} slot={3} />
              <TrendChart title="Usage trend" sub="LLM tokens per day" data={a.daily as unknown as Record<string, unknown>[]} series={[{ key: "tokens", label: "Tokens", slot: 1 }]} height={200} />
            </div>
          </>
        )}

        {data && (
          <div className="grid-3">
            <RecentConversations rows={data.recent_conversations} />
            <RecentActions title="Recent actions" rows={data.recent_actions} empty="No action executed yet." />
            <RecentActions title="Needs attention" rows={data.attention} empty="Nothing failed, pending or waiting for a human." attention />
          </div>
        )}
      </div>
    </>
  );
}

function Onboarding() {
  return (
    <Card>
      <CardHeader title="Set up your first agent" sub="Three steps before your first conversation." />
      <div className="card-body">
        <div className="grid-3">
          <Step n={1} icon={<Bot />} title="Create an agent" to="/app/agent?new=1" cta="Create agent">Pick a domain template and describe your business.</Step>
          <Step n={2} icon={<BookOpen />} title="Review its knowledge" to="/app/knowledge" cta="Open knowledge base">Edit the answers your agent may give, or import your own.</Step>
          <Step n={3} icon={<Zap />} title="Talk to it" to="/app/playground" cta="Open Playground">Test by text or voice before deploying it.</Step>
        </div>
      </div>
    </Card>
  );
}
function Step({ n, icon, title, children, to, cta }: { n: number; icon: React.ReactNode; title: string; children: React.ReactNode; to: string; cta: string }) {
  return (
    <div className="cap" style={{ flexDirection: "column", gap: 10 }}>
      <div className="row">
        <div className="cap-icon">{icon}</div>
        <span className="xsmall subtle">STEP {n}</span>
      </div>
      <div className="strong">{title}</div>
      <div className="small muted">{children}</div>
      <Link to={to} className="btn btn-secondary btn-sm" style={{ alignSelf: "flex-start" }}>{cta}</Link>
    </div>
  );
}

function RecentConversations({ rows }: { rows: ConversationRow[] }) {
  const nav = useNavigate();
  return (
    <Card>
      <CardHeader title="Latest conversations" action={<Link to="/app/conversations" className="small" style={{ color: "var(--accent-text)" }}>View all</Link>} />
      {rows.length === 0 ? (
        <EmptyState icon={<MessageSquareText />} title="No conversations yet" />
      ) : (
        <div>
          {rows.map((c) => (
            <button key={c.id} className="menu-item" style={{ padding: "10px 20px", borderRadius: 0, borderBottom: "1px solid var(--border)" }} onClick={() => nav(`/app/conversations/${c.id}`)}>
              {c.channel === "voice" ? <Mic /> : <MessageSquareText />}
              <span className="grow stack" style={{ minWidth: 0 }}>
                <span className="small strong truncate">{c.agent_name}</span>
                <span className="xsmall subtle">{relative(c.started_at)} · {c.turns} turns · {duration(c.duration_s)}</span>
              </span>
              <OutcomeBadge outcome={c.outcome} />
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}

function RecentActions({ title, rows, empty, attention }: { title: string; rows: ActionRow[]; empty: string; attention?: boolean }) {
  const nav = useNavigate();
  return (
    <Card>
      <CardHeader title={title} action={<Link to={attention ? "/app/actions?status=failed,pending,requires_human" : "/app/actions"} className="small" style={{ color: "var(--accent-text)" }}>View all</Link>} />
      {rows.length === 0 ? (
        <EmptyState icon={attention ? <AlertTriangle /> : <Workflow />} title={empty} />
      ) : (
        <div>
          {rows.map((a) => (
            <button key={a.id} className="menu-item" style={{ padding: "10px 20px", borderRadius: 0, borderBottom: "1px solid var(--border)" }} onClick={() => nav(`/app/actions?open=${a.id}`)}>
              <Workflow />
              <span className="grow stack" style={{ minWidth: 0 }}>
                <span className="small strong truncate">{a.label}</span>
                <span className="xsmall subtle truncate">
                  {relative(a.created_at)}
                  {a.type === "handoff.human" && a.details?.reason ? ` · ${escalationLabel(String(a.details.reason))}` : ""}
                </span>
              </span>
              <StatusBadge status={a.status} />
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}
