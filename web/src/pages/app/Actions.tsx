import { Fragment, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Search, Workflow, Zap } from "lucide-react";
import { api, qs } from "@/api/client";
import type { ActionRow, ActionStatus, Paged } from "@/api/types";
import { Badge, Card, Drawer, EmptyState, ErrorState, PageHeader, Pagination, Skeleton, StatusBadge } from "@/components/ui";
import { RANGES } from "@/pages/app/Conversations";
import { useAgents } from "@/lib/agents";
import { dateTime, daysAgo, escalationLabel, humanize, ms, STATUSES } from "@/lib/format";
import { useAsync, useDebounced, useDocumentTitle } from "@/lib/hooks";

export function Actions() {
  useDocumentTitle("Actions");
  const [params, setParams] = useSearchParams();
  const { agents } = useAgents();
  const [f, setF] = useState({ q: "", status: params.get("status") || "", type: "", agent_id: "", range: "all" });
  const [page, setPage] = useState(1);
  const q = useDebounced(f.q);
  const from = f.range === "all" ? undefined : daysAgo(Number(f.range) - 1);
  const { data, error, loading, reload } = useAsync(
    (s) => api.get<Paged<ActionRow> & { types: { type: string; label: string }[] }>(`/actions${qs({ q, status: f.status, type: f.type, agent_id: f.agent_id, from, page, page_size: 20 })}`, s),
    [q, f.status, f.type, f.agent_id, from, page],
  );
  const openId = params.get("open");
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    setF({ ...f, [k]: e.target.value });
    setPage(1);
  };
  const open = (id: string | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("open", id);
    else p.delete("open");
    setParams(p, { replace: true });
  };
  const multi = f.status.includes(",");

  return (
    <>
      <PageHeader title="Actions" sub="Operations the agent executed or attempted. Only real executions appear here — nothing is simulated in this list." />
      <div className="toolbar">
        <div className="input-icon" style={{ minWidth: 220, flex: "1 1 220px", maxWidth: 320 }}>
          <Search />
          <input className="input input-sm" placeholder="Search ID, conversation, reference" value={f.q} onChange={set("q")} aria-label="Search" />
        </div>
        <select className="select select-sm" style={{ width: "auto" }} value={f.range} onChange={set("range")} aria-label="Date range">
          {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
        <select className="select select-sm" style={{ width: "auto" }} value={f.status} onChange={set("status")} aria-label="Status">
          <option value="">All statuses</option>
          {multi && <option value={f.status}>Needs attention</option>}
          {(Object.keys(STATUSES) as ActionStatus[]).map((s) => <option key={s} value={s}>{STATUSES[s].label}</option>)}
        </select>
        <select className="select select-sm" style={{ width: "auto" }} value={f.type} onChange={set("type")} aria-label="Type">
          <option value="">All types</option>
          {data?.types.map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
        </select>
        <select className="select select-sm" style={{ width: "auto" }} value={f.agent_id} onChange={set("agent_id")} aria-label="Agent">
          <option value="">All agents</option>
          {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </div>
      <Card>
        {error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : loading && !data ? (
          <div className="card-body stack gap-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={28} />)}</div>
        ) : data && data.items.length === 0 ? (
          <EmptyState icon={<Workflow />} title="No actions match" action={<Link to="/app/playground" className="btn btn-secondary"><Zap /> Book something in the Playground</Link>}>
            Actions appear when the agent books, moves or cancels something, or transfers a conversation.
          </EmptyState>
        ) : data ? (
          <>
            <div className="table-wrap" style={{ opacity: loading ? 0.6 : 1 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Action ID</th>
                    <th>Type</th>
                    <th>Conversation</th>
                    <th>Executed</th>
                    <th>Status</th>
                    <th className="num">Duration</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => open(a.id)}>
                      <td className="id">{a.id}</td>
                      <td>
                        <div className="stack">
                          <span className="small strong">{a.label}</span>
                          <span className="xsmall subtle mono">{a.type}</span>
                        </div>
                      </td>
                      <td>
                        {a.conversation_id ? (
                          <Link to={`/app/conversations/${a.conversation_id}`} className="id" onClick={(e) => e.stopPropagation()} style={{ color: "var(--accent-text)" }}>
                            {a.conversation_id}
                          </Link>
                        ) : "—"}
                      </td>
                      <td className="small" style={{ whiteSpace: "nowrap" }}>{dateTime(a.updated_at)}</td>
                      <td><StatusBadge status={a.status} /></td>
                      <td className="num">{ms(a.duration_ms)}</td>
                      <td className="small muted truncate" style={{ maxWidth: 260 }}>{summary(a)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
          </>
        ) : null}
      </Card>
      <ActionDrawer id={openId} onClose={() => open(null)} />
    </>
  );
}

function summary(a: ActionRow): string {
  const d = a.details as Record<string, unknown>;
  const r = (d.result || {}) as Record<string, unknown>;
  if (a.type === "handoff.human") return escalationLabel(String(d.reason || ""));
  if (r.reference) return `Ref ${r.reference}${r.start ? ` · ${String(r.start).replace("T", " ")}` : ""}`;
  if (a.status === "pending") return "Summary read back, waiting for the customer's yes";
  if (d.error) return String(d.error);
  return d.item ? `Item ${d.item}` : "—";
}

function ActionDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { data: a, error, loading } = useAsync((s) => (id ? api.get<ActionRow>(`/actions/${id}`, s) : Promise.resolve(null)), [id]);
  const d = (a?.details || {}) as Record<string, unknown>;
  const result = d.result as Record<string, unknown> | undefined;
  return (
    <Drawer open={!!id} onClose={onClose} title={a?.label || "Action"} sub={a ? <span className="mono">{a.id}</span> : null}>
      {error ? (
        <ErrorState error={error} />
      ) : loading || !a ? (
        <Skeleton h={200} />
      ) : (
        <div className="stack gap-6">
          <div className="row wrap">
            <StatusBadge status={a.status} />
            <Badge tone="outline">{a.type}</Badge>
            {Boolean(d.imported) && <Badge>imported from test logs</Badge>}
          </div>
          <dl className="kv">
            <dt>Agent</dt><dd>{a.agent_name || "—"}</dd>
            <dt>Conversation</dt>
            <dd>{a.conversation_id ? <Link className="mono" style={{ color: "var(--accent-text)" }} to={`/app/conversations/${a.conversation_id}`}>{a.conversation_id}</Link> : "—"}</dd>
            <dt>Turn</dt><dd>{a.turn_idx ?? "—"}</dd>
            <dt>Created</dt><dd>{dateTime(a.created_at)}</dd>
            <dt>Last update</dt><dd>{dateTime(a.updated_at)}</dd>
            <dt>Tool</dt><dd className="mono">{a.tool ? `${a.tool}.${a.tool_action}` : "—"}</dd>
            <dt>Workflow</dt><dd>{a.workflow ? humanize(a.workflow) : "—"}</dd>
            <dt>Duration</dt><dd>{ms(a.duration_ms)}</dd>
            {a.type === "handoff.human" && (<><dt>Reason</dt><dd>{escalationLabel(String(d.reason || ""))}</dd></>)}
            {Boolean(d.detail) && (<><dt>Detail</dt><dd>{String(d.detail)}</dd></>)}
            {Boolean(d.error) && (<><dt>Error</dt><dd style={{ color: "var(--critical-text)" }}>{String(d.error)}</dd></>)}
          </dl>
          {result && (
            <div className="stack gap-2">
              <span className="label">Execution result</span>
              <dl className="kv">
                {Object.entries(result).map(([k, v]) => (
                  <Fragment key={k}><dt>{humanize(k)}</dt><dd className="mono">{String(v)}</dd></Fragment>
                ))}
              </dl>
            </div>
          )}
          {Boolean(d.summary) && (
            <div className="stack gap-2">
              <span className="label">Summary read to the customer</span>
              <p className="small muted">{String(d.summary)}</p>
            </div>
          )}
          <div className="stack gap-2">
            <span className="label">Raw details</span>
            <pre className="pre">{JSON.stringify(a.details, null, 2)}</pre>
          </div>
        </div>
      )}
    </Drawer>
  );
}
