import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { MessageSquareText, Mic, Search, Zap } from "lucide-react";
import { api, qs } from "@/api/client";
import type { ConversationRow, Outcome, Paged } from "@/api/types";
import { Badge, Card, EmptyState, ErrorState, OutcomeBadge, PageHeader, Pagination, Skeleton } from "@/components/ui";
import { useAgents } from "@/lib/agents";
import { dateTime, daysAgo, duration, OUTCOMES } from "@/lib/format";
import { useAsync, useDebounced, useDocumentTitle } from "@/lib/hooks";

export const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "all", label: "All time" },
];

export function Conversations() {
  useDocumentTitle("Conversations");
  const nav = useNavigate();
  const { agents } = useAgents();
  const [f, setF] = useState({ q: "", agent_id: "", channel: "", outcome: "", source: "", range: "30" });
  const [page, setPage] = useState(1);
  const q = useDebounced(f.q);
  const from = f.range === "all" ? undefined : daysAgo(Number(f.range) - 1);
  const { data, error, loading, reload } = useAsync(
    (s) => api.get<Paged<ConversationRow>>(`/conversations${qs({ q, agent_id: f.agent_id, channel: f.channel, outcome: f.outcome, source: f.source, from, page, page_size: 20 })}`, s),
    [q, f.agent_id, f.channel, f.outcome, f.source, from, page],
  );
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    setF({ ...f, [k]: e.target.value });
    setPage(1);
  };

  return (
    <>
      <PageHeader title="Conversations" sub="Every interaction with your agents. Names and phone numbers are masked before storage." />
      <div className="toolbar">
        <div className="input-icon" style={{ minWidth: 220, flex: "1 1 220px", maxWidth: 320 }}>
          <Search />
          <input className="input input-sm" placeholder="Search transcripts or IDs" value={f.q} onChange={set("q")} aria-label="Search" />
        </div>
        <select className="select select-sm" style={{ width: "auto" }} value={f.range} onChange={set("range")} aria-label="Date range">
          {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
        <select className="select select-sm" style={{ width: "auto" }} value={f.agent_id} onChange={set("agent_id")} aria-label="Agent">
          <option value="">All agents</option>
          {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
        <select className="select select-sm" style={{ width: "auto" }} value={f.channel} onChange={set("channel")} aria-label="Channel">
          <option value="">All channels</option>
          <option value="chat">Chat</option>
          <option value="voice">Voice</option>
        </select>
        <select className="select select-sm" style={{ width: "auto" }} value={f.outcome} onChange={set("outcome")} aria-label="Outcome">
          <option value="">All outcomes</option>
          {(Object.keys(OUTCOMES) as Outcome[]).map((o) => <option key={o} value={o}>{OUTCOMES[o].label}</option>)}
        </select>
        <select className="select select-sm" style={{ width: "auto" }} value={f.source} onChange={set("source")} aria-label="Source">
          <option value="">All sources</option>
          <option value="playground">Playground</option>
          <option value="import">Imported test logs</option>
        </select>
      </div>
      <Card>
        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : loading && !data ? (
          <div className="card-body stack gap-3">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} h={28} />)}</div>
        ) : data && data.items.length === 0 ? (
          <EmptyState icon={<MessageSquareText />} title="No conversations match" action={<Link to="/app/playground" className="btn btn-secondary"><Zap /> Start one in the Playground</Link>}>
            Try a wider date range or remove a filter.
          </EmptyState>
        ) : data ? (
          <>
            <div className="table-wrap" style={{ opacity: loading ? 0.6 : 1 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Conversation</th>
                    <th>Customer</th>
                    <th>Channel</th>
                    <th>Started</th>
                    <th className="num">Duration</th>
                    <th className="num">Turns</th>
                    <th>Status</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((c) => (
                    <tr key={c.id} className="clickable" onClick={() => nav(`/app/conversations/${c.id}`)}>
                      <td>
                        <div className="stack" style={{ maxWidth: 320 }}>
                          <span className="id">{c.id}</span>
                          <span className="small truncate muted">{c.first_message || "—"}</span>
                        </div>
                      </td>
                      <td>
                        <div className="stack">
                          <span className="mono small">{c.customer_ref}</span>
                          <span className="xsmall subtle">{c.agent_name}</span>
                        </div>
                      </td>
                      <td>
                        <span className="row small">{c.channel === "voice" ? <Mic size={14} /> : <MessageSquareText size={14} />}{c.channel === "voice" ? "Voice" : "Chat"}</span>
                        {c.source === "import" && <Badge tone="outline">imported</Badge>}
                      </td>
                      <td className="small" style={{ whiteSpace: "nowrap" }}>{dateTime(c.started_at)}</td>
                      <td className="num">{duration(c.duration_s)}</td>
                      <td className="num">{c.turns}</td>
                      <td>{c.status === "active" ? <Badge tone="accent"><span className="dot" />Live</Badge> : <Badge>Ended</Badge>}</td>
                      <td><OutcomeBadge outcome={c.outcome} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        ) : null}
      </Card>
    </>
  );
}
