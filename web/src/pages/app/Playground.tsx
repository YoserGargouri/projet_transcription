import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle, ArrowUp, Bot, Brain, Check, CheckCircle2, ExternalLink, Keyboard, Mic, RotateCcw, Square, UserRound, Volume2, Wrench,
} from "lucide-react";
import { api, ApiError } from "@/api/client";
import type { AgentState, Integrations, PlaygroundSession, TurnDetails, TurnResponse } from "@/api/types";
import { Alert, Badge, Button, Card, CardHeader, Segmented } from "@/components/ui";
import { NoAgent } from "@/pages/app/AgentConfig";
import { useAgents } from "@/lib/agents";
import { escalationLabel, humanize, ms, timeOnly } from "@/lib/format";
import { useAsync, useDocumentTitle } from "@/lib/hooks";
import { WavRecorder } from "@/lib/recorder";

interface Msg {
  id: string;
  role: "agent" | "user" | "system";
  text: string;
  at: string;
  turn?: TurnResponse;
  voice?: boolean;
  audioUrl?: string;
  error?: boolean;
}

const nowIso = () => new Date().toISOString().slice(0, 19);
let seq = 0;
const mid = () => `m${++seq}`;

export function Playground() {
  useDocumentTitle("Playground");
  const { current, loading } = useAgents();
  if (!loading && !current) return <NoAgent />;
  if (!current) return null;
  return <Session key={current.id} agentId={current.id} agentName={current.name} />;
}

function Session({ agentId, agentName }: { agentId: string; agentName: string }) {
  const [session, setSession] = useState<PlaygroundSession | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [state, setState] = useState<AgentState | null>(null);
  const [lastTurn, setLastTurn] = useState<TurnResponse | null>(null);
  const [starting, setStarting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [mode, setMode] = useState<"text" | "voice">("text");
  const [text, setText] = useState("");
  const [totals, setTotals] = useState({ turns: 0, tokens: 0, latency: 0, llm: 0 });
  const logRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<string | null>(null);
  const integrations = useAsync((s) => api.get<Integrations>("/integrations", s), []);

  const push = (m: Omit<Msg, "id">) => setMessages((x) => [...x, { ...m, id: mid() }]);

  const end = useCallback(() => {
    const id = sessionRef.current;
    if (id) api.post(`/playground/sessions/${id}/end`).catch(() => {});
    sessionRef.current = null;
  }, []);

  const start = useCallback(async () => {
    end();
    setStarting(true);
    setStartError(null);
    setExpired(false);
    setMessages([]);
    setLastTurn(null);
    setTotals({ turns: 0, tokens: 0, latency: 0, llm: 0 });
    try {
      const s = await api.post<PlaygroundSession>("/playground/sessions", { agent_id: agentId });
      sessionRef.current = s.conversation_id;
      setSession(s);
      setState(s.state);
      setMessages([{ id: mid(), role: "agent", text: s.greeting, at: s.created_at }]);
      if (!s.voice_available) setMode("text");
    } catch (e) {
      setStartError((e as Error).message);
    } finally {
      setStarting(false);
    }
  }, [agentId, end]);

  useEffect(() => {
    start();
    return () => end();
  }, [start, end]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const onTurn = (t: TurnResponse, voice: boolean) => {
    setState(t.state);
    setLastTurn(t);
    setTotals((x) => ({ turns: x.turns + 1, tokens: x.tokens + t.tokens, latency: x.latency + t.latency_ms, llm: x.llm + (t.llm_used ? 1 : 0) }));
    push({ role: "agent", text: t.reply, at: t.created_at, turn: t, voice, audioUrl: t.audio_url });
  };
  const onError = (e: unknown) => {
    if (e instanceof ApiError && e.status === 404) setExpired(true);
    push({ role: "system", text: (e as Error).message, at: nowIso(), error: true });
  };

  const sendText = async (e?: FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || !session || busy) return;
    setText("");
    push({ role: "user", text: t, at: nowIso() });
    setBusy(true);
    try {
      onTurn(await api.post<TurnResponse>(`/playground/sessions/${session.conversation_id}/messages`, { text: t }), false);
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
    }
  };

  const sendVoice = async (blob: Blob) => {
    if (!session) return;
    setBusy(true);
    const pending = mid();
    setMessages((x) => [...x, { id: pending, role: "user", text: "Transcribing…", at: nowIso(), voice: true }]);
    try {
      const fd = new FormData();
      fd.append("audio", blob, "turn.wav");
      const t = await api.post<TurnResponse>(`/playground/sessions/${session.conversation_id}/voice`, fd);
      setMessages((x) => x.map((m) => (m.id === pending ? { ...m, text: t.transcript || "(nothing understood)" } : m)));
      onTurn(t, true);
    } catch (err) {
      setMessages((x) => x.filter((m) => m.id !== pending));
      onError(err);
    } finally {
      setBusy(false);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendText();
    }
  };

  const llm = integrations.data?.llm;
  const ended = state?.escalated;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Playground</h1>
          <p>Talk to <b>{agentName}</b> exactly as a customer would. Conversations here are recorded in your history like any other.</p>
        </div>
        <div className="row wrap">
          {session && (
            <Segmented
              label="Interaction mode"
              value={mode}
              onChange={setMode}
              options={[
                { value: "text", label: "Text", icon: <Keyboard /> },
                ...(session.voice_available ? [{ value: "voice" as const, label: "Voice", icon: <Mic /> }] : []),
              ]}
            />
          )}
          <Button size="sm" icon={<RotateCcw />} onClick={start} loading={starting}>
            New conversation
          </Button>
        </div>
      </div>

      {session && !session.llm_enabled && (
        <div style={{ marginBottom: 12 }}>
          <Alert tone="warning">No language model is configured on the server (LLM_BASE_URL / LLM_MODEL). The agent runs on rules only.</Alert>
        </div>
      )}

      <div className="pg">
        <Card className="chat">
          <div className="chat-head">
            <div className="row">
              <span className="avatar" style={{ borderRadius: 6, background: "var(--primary)", color: "var(--primary-text)" }}><Bot size={14} /></span>
              <div className="stack">
                <span className="small strong">{agentName}</span>
                <span className="xsmall subtle">
                  {session ? (session.mode === "llm_first" ? "LLM-first" : "Rules-first") : "…"}
                  {llm?.model ? ` · ${llm.model}` : ""}
                </span>
              </div>
            </div>
            {session && (
              <Link to={`/app/conversations/${session.conversation_id}`} className="small row" style={{ color: "var(--text-3)" }}>
                {session.conversation_id} <ExternalLink size={12} />
              </Link>
            )}
          </div>

          <div className="chat-log" ref={logRef} aria-live="polite">
            {startError && <Alert tone="critical">Could not start the conversation: {startError}</Alert>}
            {starting && <div className="typing"><span /><span /><span /></div>}
            {messages.map((m) => <Message key={m.id} m={m} autoplay={mode === "voice"} />)}
            {busy && (
              <div className="msg agent">
                <div className="msg-avatar"><Bot /></div>
                <div className="msg-body">
                  <div className="bubble" style={{ padding: 0 }}><div className="typing"><span /><span /><span /></div></div>
                  <div className="msg-meta">{mode === "voice" ? "Transcribing, understanding and synthesizing…" : "Understanding…"}</div>
                </div>
              </div>
            )}
          </div>

          <div className="composer">
            {expired || ended ? (
              <div className="row-between wrap">
                <span className="small muted">
                  {ended ? "This conversation was transferred to a human. Start a new one to keep testing." : "This conversation expired."}
                </span>
                <Button variant="primary" size="sm" icon={<RotateCcw />} onClick={start}>New conversation</Button>
              </div>
            ) : mode === "voice" ? (
              <VoicePad disabled={!session || busy} onRecorded={sendVoice} sessionId={session?.conversation_id} />
            ) : (
              <form onSubmit={sendText}>
                <textarea
                  className="textarea"
                  rows={1}
                  placeholder="Write as a customer would… (Enter to send, Shift+Enter for a new line)"
                  value={text}
                  maxLength={2000}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={onKey}
                  disabled={!session}
                  aria-label="Message"
                />
                <Button variant="primary" type="submit" icon={<ArrowUp />} disabled={!text.trim() || !session || busy} aria-label="Send" />
              </form>
            )}
          </div>
        </Card>

        <div className="inspector">
          <StatePanel state={state} />
          <TurnPanel turn={lastTurn} />
          <Card>
            <CardHeader title="This conversation" />
            <div className="card-body">
              <dl className="kv">
                <dt>Turns</dt><dd className="num">{totals.turns}</dd>
                <dt>LLM used</dt><dd className="num">{totals.llm} / {totals.turns}</dd>
                <dt>Tokens</dt><dd className="num">{totals.tokens.toLocaleString("en-US")}</dd>
                <dt>Avg latency</dt><dd className="num">{totals.turns ? ms(totals.latency / totals.turns) : "—"}</dd>
              </dl>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function Message({ m, autoplay }: { m: Msg; autoplay: boolean }) {
  if (m.role === "system")
    return (
      <div className="msg system">
        <div className="bubble" style={m.error ? { color: "var(--critical-text)" } : undefined}>
          {m.error && <AlertTriangle size={12} style={{ display: "inline", marginRight: 4, verticalAlign: -2 }} />}
          {m.text}
        </div>
      </div>
    );
  const t = m.turn;
  return (
    <div className={`msg ${m.role}`}>
      <div className="msg-avatar">{m.role === "agent" ? <Bot /> : <UserRound />}</div>
      <div className="msg-body">
        <div className="bubble">{m.text}</div>
        {m.audioUrl && <audio src={m.audioUrl} controls autoPlay={autoplay} preload="auto" style={{ height: 32, maxWidth: 280 }} />}
        <div className="msg-meta">
          <span>{timeOnly(m.at)}</span>
          {m.role === "user" && m.voice && <span>· transcribed</span>}
          {t && (
            <>
              {t.llm_used ? <Badge tone="accent" icon={<Brain />}>LLM</Badge> : t.llm_failed ? <Badge tone="warning" icon={<Wrench />}>Rules (LLM unavailable)</Badge> : <Badge icon={<Wrench />}>Rules</Badge>}
              {t.intent && <span>{humanize(t.intent)}</span>}
              <span>· {ms(t.latency_ms)}</span>
              {t.details.knowledge_used?.length ? <Badge tone="info">Sources: {t.details.knowledge_used.join(", ")}</Badge> : null}
              {t.details.action?.status === "succeeded" && <Badge tone="good" icon={<CheckCircle2 />}>Action executed</Badge>}
              {t.details.action?.status === "failed" && <Badge tone="critical">Action failed</Badge>}
              {t.escalated && <Badge tone="warning" icon={<UserRound />}>Transferred: {escalationLabel(t.escalation_reason)}</Badge>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function VoicePad({ disabled, onRecorded, sessionId }: { disabled: boolean; onRecorded: (b: Blob) => void; sessionId?: string }) {
  const rec = useRef<WavRecorder | null>(null);
  const [recording, setRecording] = useState(false);
  const [level, setLevel] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [greeting, setGreeting] = useState<string | null>(null);
  const [greetingBusy, setGreetingBusy] = useState(false);
  useEffect(() => () => rec.current?.cancel(), []);

  if (!WavRecorder.supported()) return <Alert tone="warning">This browser cannot record audio. Use a recent Chrome, Edge or Firefox over http://localhost or HTTPS.</Alert>;

  const toggle = async () => {
    setErr(null);
    if (!recording) {
      try {
        const r = new WavRecorder();
        r.onLevel = setLevel;
        await r.start();
        rec.current = r;
        setRecording(true);
      } catch {
        setErr("Microphone access was refused or is unavailable.");
      }
      return;
    }
    setRecording(false);
    setLevel(0);
    const r = rec.current;
    rec.current = null;
    if (!r) return;
    const { blob, seconds } = await r.stop();
    if (seconds < 0.4) return setErr("Recording too short. Hold on a little longer.");
    onRecorded(blob);
  };

  const playGreeting = async () => {
    if (!sessionId) return;
    setGreetingBusy(true);
    try {
      const r = await api.post<{ audio_url: string | null }>(`/playground/sessions/${sessionId}/greeting-audio`);
      setGreeting(r.audio_url);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setGreetingBusy(false);
    }
  };

  return (
    <div className="voice-pad">
      <button className={`mic ${recording ? "recording" : ""}`} onClick={toggle} disabled={disabled && !recording} aria-label={recording ? "Stop and send" : "Start recording"}>
        {recording ? <Square /> : <Mic />}
      </button>
      {recording ? (
        <div className="level" aria-hidden><span style={{ width: `${Math.round(level * 100)}%` }} /></div>
      ) : (
        <span className="xsmall subtle">{disabled ? "Processing the previous turn…" : "Click to speak, click again to send"}</span>
      )}
      {err && <span className="xsmall" style={{ color: "var(--critical-text)" }}>{err}</span>}
      <div className="row">
        {greeting ? (
          <audio src={greeting} controls autoPlay style={{ height: 30 }} />
        ) : (
          <Button size="sm" variant="ghost" icon={<Volume2 />} onClick={playGreeting} loading={greetingBusy} disabled={!sessionId}>
            Hear the greeting
          </Button>
        )}
      </div>
    </div>
  );
}

function StatePanel({ state }: { state: AgentState | null }) {
  return (
    <Card>
      <CardHeader title="What the agent understood" sub="Live state of the conversation" />
      <div className="card-body">
        {!state || (!state.workflow && !state.intent) ? (
          <p className="small subtle">No request identified yet.</p>
        ) : (
          <div className="stack gap-3">
            <div className="row wrap">
              {state.intent && <Badge tone="accent">{humanize(state.intent)}</Badge>}
              {state.awaiting_confirmation && <Badge tone="info">Waiting for confirmation</Badge>}
              {state.escalated && <Badge tone="warning">Transferred</Badge>}
            </div>
            {state.workflow && (
              <>
                <div className="small muted">{state.workflow_description}</div>
                <div className="field-list">
                  {state.fields?.map((f) => (
                    <div className="field-row" key={f.name}>
                      <span className="row">
                        <span className={`check ${f.filled ? "on" : ""}`}>{f.filled && <Check />}</span>
                        {humanize(f.name)}
                      </span>
                      <span className="small muted truncate" style={{ maxWidth: 160 }}>{f.value || (f.required ? "missing" : "optional")}</span>
                    </div>
                  ))}
                </div>
                {state.candidates ? <span className="xsmall subtle">{state.candidates} catalogue candidates under consideration</span> : null}
              </>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

function TurnPanel({ turn }: { turn: TurnResponse | null }) {
  const d: TurnDetails | undefined = turn?.details;
  return (
    <Card>
      <CardHeader title="Last turn" sub="How the reply was produced" />
      <div className="card-body">
        {!turn || !d ? (
          <p className="small subtle">Send a message to see the decision trace.</p>
        ) : (
          <dl className="kv">
            <dt>Understanding</dt>
            <dd>{turn.llm_used ? "Language model" : turn.llm_failed ? `Rules (LLM ${d.llm_failure || "error"})` : "Rules"}</dd>
            {d.llm?.intent && (<><dt>Intent</dt><dd>{humanize(d.llm.intent)}{d.llm.understood === false ? " (not understood)" : ""}</dd></>)}
            {d.rules_hint && (<><dt>Rules hint</dt><dd>{humanize(d.rules_hint)}</dd></>)}
            {d.llm?.asks_for && (<><dt>Asks for</dt><dd>{humanize(d.llm.asks_for)}</dd></>)}
            {d.knowledge_used?.length ? (<><dt>Sources</dt><dd>{d.knowledge_used.join(", ")}</dd></>) : null}
            {d.knowledge_unsupported && (<><dt>Grounding</dt><dd>Answer had no source: replaced</dd></>)}
            {d.precheck && (<><dt>Tool check</dt><dd>{d.precheck.reason}{d.precheck.options.length ? ` · ${d.precheck.options.length} alternatives` : ""}</dd></>)}
            {d.action && (<><dt>Action</dt><dd>{d.action.tool}.{d.action.action} · {d.action.status} · {ms(d.action.duration_ms)}</dd></>)}
            {d.tool_result?.reference ? (<><dt>Reference</dt><dd className="mono">{String(d.tool_result.reference)}</dd></>) : null}
            {d.escalation && (<><dt>Hand-off</dt><dd>{escalationLabel(d.escalation.reason)}</dd></>)}
            <dt>Latency</dt><dd>{ms(turn.latency_ms)}</dd>
            {d.timings && (
              <>
                <dt>Voice stages</dt>
                <dd>STT {d.timings.stt_s}s · agent {d.timings.agent_s}s · TTS {d.timings.tts_s}s ({d.timings.tts_engine}{d.timings.tts_cached ? ", cached" : ""})</dd>
                {d.timings.stt_confidence !== undefined && (<><dt>STT confidence</dt><dd>{Math.round((d.timings.stt_confidence || 0) * 100)}%</dd></>)}
              </>
            )}
            <dt>Tokens</dt><dd>{turn.tokens}</dd>
          </dl>
        )}
      </div>
    </Card>
  );
}
