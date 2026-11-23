import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Bot, Brain, CheckCircle2, Mic, Trash2, UserRound, Wrench } from "lucide-react";
import { api } from "@/api/client";
import type { ConversationDetail, Turn } from "@/api/types";
import { Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, ErrorState, OutcomeBadge, Skeleton, StatusBadge } from "@/components/ui";
import { dateTime, duration, escalationLabel, humanize, ms, num, timeOnly } from "@/lib/format";
import { useAsync, useDocumentTitle } from "@/lib/hooks";
import { useToast } from "@/lib/ui-state";

export function ConversationView() {
  const { id = "" } = useParams();
  useDocumentTitle(`Conversation ${id}`);
  const nav = useNavigate();
  const toast = useToast();
  const { data: c, error, loading, reload } = useAsync((s) => api.get<ConversationDetail>(`/conversations/${id}`, s), [id]);
  const [showTrace, setShowTrace] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !c) return <Skeleton h={480} />;

  const remove = async () => {
    setDeleting(true);
    try {
      await api.del(`/conversations/${id}`);
      toast("Conversation deleted");
      nav("/app/conversations");
    } catch (e) {
      toast((e as Error).message, "critical");
      setDeleting(false);
    }
  };

  return (
    <>
      <Link to="/app/conversations" className="row small muted" style={{ marginBottom: 12 }}>
        <ArrowLeft size={14} /> Conversations
      </Link>
      <div className="page-header">
        <div>
          <h1 className="row" style={{ gap: 10 }}>
            <span className="mono" style={{ fontSize: "var(--fs-xl)" }}>{c.id}</span>
            <OutcomeBadge outcome={c.outcome} />
          </h1>
          <p>
            {c.agent_name} · {c.channel === "voice" ? "Voice" : "Chat"} · {dateTime(c.started_at)} · {c.source === "import" ? "imported from test logs" : c.source}
          </p>
        </div>
        <div className="row">
          <Button size="sm" variant="ghost" onClick={() => setShowTrace((v) => !v)}>{showTrace ? "Hide" : "Show"} decision trace</Button>
          <Button size="sm" variant="danger" icon={<Trash2 />} onClick={() => setConfirm(true)}>Delete</Button>
        </div>
      </div>

      <div className="split-21">
        <Card>
          <CardHeader title="Transcript" sub="Stored after anonymisation: personal details appear as [NOM], [TELEPHONE]…" />
          <div className="card-body">
            <div className="transcript">
              {c.turns_list.map((t) => <TurnRows key={t.id} t={t} trace={showTrace} />)}
            </div>
          </div>
        </Card>
        <div className="stack gap-4">
          <Card>
            <CardHeader title="Summary" />
            <div className="card-body">
              <dl className="kv">
                <dt>Customer</dt><dd className="mono">{c.customer_ref}</dd>
                <dt>Status</dt><dd>{c.status === "active" ? "Live" : "Ended"}</dd>
                <dt>Duration</dt><dd>{duration(c.duration_s)}</dd>
                <dt>Turns</dt><dd>{c.turns}</dd>
                <dt>LLM calls</dt><dd>{c.llm_calls}</dd>
                <dt>Tokens</dt><dd>{num(c.prompt_tokens + c.completion_tokens)}</dd>
                {c.channel === "voice" && (<><dt>Voice chars</dt><dd>{num(c.tts_chars)}</dd><dt>Audio in</dt><dd>{c.stt_seconds.toFixed(1)} s</dd></>)}
                {c.escalation_reason && (<><dt>Hand-off</dt><dd>{escalationLabel(c.escalation_reason)}</dd></>)}
              </dl>
            </div>
          </Card>
          <Card>
            <CardHeader title="Actions triggered" sub={`${c.actions.length} in this conversation`} />
            {c.actions.length === 0 ? (
              <EmptyState icon={<Wrench />} title="No action" />
            ) : (
              <div className="card-body stack gap-3">
                {c.actions.map((a) => (
                  <div key={a.id} className="cap" style={{ flexDirection: "column", gap: 6 }}>
                    <div className="row-between">
                      <span className="small strong">{a.label}</span>
                      <StatusBadge status={a.status} />
                    </div>
                    <span className="xsmall subtle mono">{a.id} · turn {a.turn_idx ?? "—"}{a.duration_ms ? ` · ${ms(a.duration_ms)}` : ""}</span>
                    {Boolean((a.details.result as Record<string, unknown> | undefined)?.reference) && (
                      <span className="small">Reference <b className="mono">{String((a.details.result as Record<string, unknown>).reference)}</b></span>
                    )}
                    {a.type === "handoff.human" && <span className="small muted">{escalationLabel(String(a.details.reason || ""))}</span>}
                    <Link to={`/app/actions?open=${a.id}`} className="xsmall" style={{ color: "var(--accent-text)" }}>Details</Link>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
      <ConfirmDialog open={confirm} title="Delete this conversation?" body="The transcript, its actions and its audio files are deleted permanently." onClose={() => setConfirm(false)} onConfirm={remove} loading={deleting} />
    </>
  );
}

function TurnRows({ t, trace }: { t: Turn; trace: boolean }) {
  const d = t.details;
  return (
    <>
      {t.user_text && (
        <div className="t-turn user">
          <div className="t-who row"><UserRound size={13} /> Customer</div>
          <div className="t-text">
            {t.user_text}
            {t.channel === "voice" && <span className="xsmall subtle"> <Mic size={11} style={{ display: "inline", verticalAlign: -1 }} /> transcribed</span>}
          </div>
        </div>
      )}
      <div className="t-turn agent">
        <div className="t-who row"><Bot size={13} /> Agent</div>
        <div className="stack gap-2">
          <div className="t-text">{t.agent_text}</div>
          {t.audio_url && <audio src={t.audio_url} controls preload="none" style={{ height: 30, maxWidth: 300 }} />}
          <div className="msg-meta">
            <span>{timeOnly(t.created_at)}</span>
            {!d.greeting && (t.llm_used ? <Badge tone="accent" icon={<Brain />}>LLM</Badge> : t.llm_failed ? <Badge tone="warning">Rules (LLM unavailable)</Badge> : <Badge>Rules</Badge>)}
            {t.intent && !d.greeting && <span>{humanize(t.intent)}</span>}
            {t.latency_ms !== null && <span>· {ms(t.latency_ms)}</span>}
            {d.knowledge_used?.length ? <Badge tone="info">Sources: {d.knowledge_used.join(", ")}</Badge> : null}
            {d.action?.status === "succeeded" && <Badge tone="good" icon={<CheckCircle2 />}>Action executed</Badge>}
            {d.escalation && <Badge tone="warning">Transferred: {escalationLabel(d.escalation.reason)}</Badge>}
          </div>
          {trace && !d.greeting && <pre className="pre">{JSON.stringify(d, null, 2)}</pre>}
        </div>
      </div>
    </>
  );
}
