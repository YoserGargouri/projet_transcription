import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight, BookOpen, Bot, Brain, CalendarCheck, Globe, Lock, MessageSquareText, Mic, Phone, ShieldAlert, ShieldCheck, Sparkles, Wrench, Zap,
} from "lucide-react";
import { api } from "@/api/client";
import type { Agent, AgentSettings, Template } from "@/api/types";
import { Alert, Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, ErrorState, Field, PageHeader, Skeleton, Switch } from "@/components/ui";
import { useAgents } from "@/lib/agents";
import { dateTime } from "@/lib/format";
import { useAsync, useDocumentTitle } from "@/lib/hooks";
import { useToast } from "@/lib/ui-state";

const DOMAINS = ["Healthcare administration", "Hospitality", "Real estate", "Automotive services", "Retail & e-commerce", "Professional services", "Education & training", "Other"];

export function AgentConfig() {
  useDocumentTitle("AI Agent");
  const [params] = useSearchParams();
  const { agents, current, loading } = useAgents();
  if (loading) return <Skeleton h={400} />;
  if (params.get("new") || agents.length === 0) return <CreateAgent first={agents.length === 0} />;
  if (!current) return null;
  return <EditAgent key={current.id} agentId={current.id} />;
}

// ======================================================================== creation
function CreateAgent({ first }: { first: boolean }) {
  const { data: templates, error, loading, reload } = useAsync((s) => api.get<Template[]>("/templates", s), []);
  const { reload: reloadAgents, select } = useAgents();
  const nav = useNavigate();
  const toast = useToast();
  const [form, setForm] = useState({ name: "", template: "", business_domain: "", business_type: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (templates?.length && !form.template) setForm((f) => ({ ...f, template: templates[0].id }));
  }, [templates, form.template]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const a = await api.post<Agent>("/agents", form);
      await reloadAgents();
      select(a.id);
      toast(`Agent “${a.name}” created with ${a.knowledge_entries} knowledge entries`);
      nav("/app/agent", { replace: true });
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const chosen = templates?.find((t) => t.id === form.template);

  return (
    <>
      <PageHeader title={first ? "Create your first agent" : "New agent"} sub="Start from a domain template, then tell us about the business it serves. You can change everything later." />
      {error && <ErrorState error={error} onRetry={reload} />}
      <form onSubmit={submit} className="stack gap-6" style={{ maxWidth: 920 }}>
        <Card>
          <CardHeader title="1. Domain template" sub="Templates define intents, workflows, tools and guard-rails. Your knowledge and settings are layered on top." />
          <div className="card-body">
            {loading ? (
              <Skeleton h={120} />
            ) : (
              <div className="template-grid">
                {templates?.map((t) => (
                  <label key={t.id} className={`option-card ${form.template === t.id ? "selected" : ""}`}>
                    <input type="radio" name="template" value={t.id} checked={form.template === t.id} onChange={set("template")} />
                    <div className="stack gap-2">
                      <div className="strong">{t.name}</div>
                      <div className="small muted">{t.description}</div>
                      <div className="row wrap">
                        <Badge>{t.workflows.length} workflows</Badge>
                        <Badge>{t.knowledge_entries} FAQ entries</Badge>
                        {t.voice && <Badge tone="accent">Voice</Badge>}
                        <Badge tone="outline">{t.language.toUpperCase()}</Badge>
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            )}
            {chosen && (
              <div className="small muted" style={{ marginTop: 12 }}>
                Can do: {chosen.workflows.map((w) => w.action_label || w.description).join(" · ")}
              </div>
            )}
          </div>
        </Card>
        <Card>
          <CardHeader title="2. Your business" sub="Shown in your workspace and kept with the agent for future automatic configuration." />
          <div className="card-body form-grid">
            <Field label="Agent name" htmlFor="a-name" hint="Internal name, e.g. “Reception — main site”.">
              <input id="a-name" className="input" required maxLength={80} value={form.name} onChange={set("name")} />
            </Field>
            <div className="grid-2">
              <Field label="Business domain" htmlFor="a-dom">
                <select id="a-dom" className="select" value={form.business_domain} onChange={set("business_domain")}>
                  <option value="">Select…</option>
                  {DOMAINS.map((d) => <option key={d}>{d}</option>)}
                </select>
              </Field>
              <Field label="Business type" htmlFor="a-type" hint="e.g. Medical imaging centre">
                <input id="a-type" className="input" maxLength={120} value={form.business_type} onChange={set("business_type")} />
              </Field>
            </div>
            <Field label="Business description" htmlFor="a-desc" hint="What you do, who calls you, what they usually ask for.">
              <textarea id="a-desc" className="textarea" rows={4} maxLength={3000} value={form.description} onChange={set("description")} />
            </Field>
            {err && <Alert tone="critical">{err}</Alert>}
          </div>
          <div className="card-footer row-between">
            <span className="xsmall subtle">The template's knowledge base is copied into this agent; edits never affect other agents.</span>
            <Button variant="primary" type="submit" loading={busy} disabled={!form.template || !form.name.trim()}>
              Create agent <ArrowRight />
            </Button>
          </div>
        </Card>
      </form>
    </>
  );
}

// ======================================================================== edition
type Draft = {
  name: string; business_domain: string; business_type: string; description: string;
  persona_name: string; greeting: string; style: string; llm_mode: AgentSettings["llm_mode"];
  voice_engine: "elevenlabs" | "gtts" | null; web_chat: boolean; voice: boolean;
};

function toDraft(a: Agent): Draft {
  return {
    name: a.name, business_domain: a.business_domain, business_type: a.business_type, description: a.description,
    persona_name: a.settings.persona_name, greeting: a.settings.greeting, style: a.settings.style,
    llm_mode: a.settings.llm_mode, voice_engine: a.settings.voice_engine, web_chat: a.settings.channels.web_chat, voice: a.settings.channels.voice,
  };
}

function EditAgent({ agentId }: { agentId: string }) {
  const { data: agent, error, loading, reload, setData } = useAsync((s) => api.get<Agent>(`/agents/${agentId}`, s), [agentId]);
  const { reload: reloadAgents } = useAgents();
  const toast = useToast();
  const nav = useNavigate();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    if (agent) setDraft(toDraft(agent));
  }, [agent]);

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !agent || !draft) return <Skeleton h={480} />;
  const t = agent.template_info;
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(agent));
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft({ ...draft, [k]: v });

  const save = async () => {
    setSaving(true);
    try {
      const a = await api.patch<Agent>(`/agents/${agentId}`, {
        name: draft.name, business_domain: draft.business_domain, business_type: draft.business_type, description: draft.description,
        settings: {
          persona_name: draft.persona_name, greeting: draft.greeting, style: draft.style, llm_mode: draft.llm_mode,
          ...(draft.voice_engine ? { voice_engine: draft.voice_engine } : {}),
          channels: { web_chat: draft.web_chat, voice: draft.voice },
        },
      });
      setData(a);
      reloadAgents();
      toast("Agent saved. New conversations use this configuration.");
    } catch (e) {
      toast((e as Error).message, "critical");
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    setDeleting(true);
    try {
      await api.del(`/agents/${agentId}`);
      await reloadAgents();
      toast("Agent deleted");
      nav("/app");
    } catch (e) {
      toast((e as Error).message, "critical");
      setDeleting(false);
    }
  };

  return (
    <>
      <PageHeader
        title={agent.name}
        sub={<>Template: {t?.name || agent.template} · updated {dateTime(agent.updated_at)} · {agent.conversations} conversations</>}
        actions={
          <Link to="/app/playground" className="btn btn-secondary btn-sm">
            <Zap /> Test in Playground
          </Link>
        }
      />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Sections">
          <a href="#identity">Business</a>
          <a href="#persona">Personality</a>
          <a href="#understanding">Understanding</a>
          <a href="#channels">Channels & voice</a>
          <a href="#capabilities">Capabilities</a>
          <a href="#knowledge">Knowledge</a>
          <a href="#danger">Delete</a>
        </nav>
        <div>
          <Section id="identity" title="Business" text="Who the agent works for. Kept with the agent and shown to your team.">
            <Field label="Agent name" htmlFor="e-name">
              <input id="e-name" className="input" maxLength={80} value={draft.name} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <div className="grid-2">
              <Field label="Business domain" htmlFor="e-dom">
                <select id="e-dom" className="select" value={draft.business_domain} onChange={(e) => set("business_domain", e.target.value)}>
                  <option value="">Select…</option>
                  {DOMAINS.map((d) => <option key={d}>{d}</option>)}
                </select>
              </Field>
              <Field label="Business type" htmlFor="e-type">
                <input id="e-type" className="input" maxLength={120} value={draft.business_type} onChange={(e) => set("business_type", e.target.value)} />
              </Field>
            </div>
            <Field label="Business description" htmlFor="e-desc">
              <textarea id="e-desc" className="textarea" rows={4} maxLength={3000} value={draft.description} onChange={(e) => set("description", e.target.value)} />
            </Field>
            <div className="notice">
              <Sparkles />
              <span>
                <b>Roadmap:</b> generate the full agent configuration — intents, workflows, knowledge draft — from this description. Today the
                description is stored; behaviour comes from the template and the settings below.
              </span>
            </div>
          </Section>

          <Section id="persona" title="Personality" text="How the agent introduces itself and speaks. Used in every reply the model writes.">
            <Field label="Introduces itself as" htmlFor="e-pn" hint="Inserted in the model instructions, e.g. “l'assistant du centre d'imagerie”.">
              <input id="e-pn" className="input" maxLength={120} value={draft.persona_name} onChange={(e) => set("persona_name", e.target.value)} />
            </Field>
            <Field label="Greeting" htmlFor="e-greet" hint="First sentence of every conversation, spoken in voice mode.">
              <textarea id="e-greet" className="textarea" rows={3} maxLength={500} value={draft.greeting} onChange={(e) => set("greeting", e.target.value)} />
            </Field>
            <Field label="Communication style" htmlFor="e-style" hint="Tone and form instructions for the model.">
              <textarea id="e-style" className="textarea" rows={3} maxLength={1500} value={draft.style} onChange={(e) => set("style", e.target.value)} />
            </Field>
          </Section>

          <Section id="understanding" title="Understanding" text="Who interprets each customer turn. Guard-rails, safety scripts, confirmations and actions stay deterministic in both modes.">
            <div className="stack gap-2">
              <Choice selected={draft.llm_mode === "llm_first"} onSelect={() => set("llm_mode", "llm_first")} icon={<Brain />} title="LLM-first (recommended)" badge="1 model call per turn">
                The language model understands every turn — intent, details, follow-ups, transcription errors — and writes the reply from your knowledge base. Rules become hints and the fallback if the model is unavailable.
              </Choice>
              <Choice selected={draft.llm_mode === "rules_first"} onSelect={() => set("llm_mode", "rules_first")} icon={<Wrench />} title="Rules-first" badge="0–1 call per turn">
                Keyword rules qualify the request; the model is only called when rules are not enough. Knowledge answers are read verbatim. Cheaper, less flexible.
              </Choice>
            </div>
            <Field label="Languages" htmlFor="e-lang" hint="Set by the template. Multi-language agents are on the roadmap.">
              <div className="row"><Globe size={16} className="subtle" /><Badge tone="outline">{(agent.settings.language || "fr").toUpperCase()}</Badge></div>
            </Field>
          </Section>

          <Section id="channels" title="Channels & voice" text="Where customers can reach this agent.">
            <div className="stack gap-3">
              <ChannelRow icon={<MessageSquareText />} title="Web chat" text="Text conversations (Playground today; embeddable widget on the roadmap).">
                <Switch checked={draft.web_chat} onChange={(v) => set("web_chat", v)} />
              </ChannelRow>
              <ChannelRow icon={<Mic />} title="Voice" text={t?.voice ? "Speech-to-text, agent, then speech synthesis." : "This template has no voice channel."}>
                <Switch checked={draft.voice && !!t?.voice} disabled={!t?.voice} onChange={(v) => set("voice", v)} />
              </ChannelRow>
              <ChannelRow icon={<Phone />} title="Phone number" text="Inbound calls over a telephone line (SIP / provider integration).">
                <Badge>Roadmap</Badge>
              </ChannelRow>
            </div>
            {t?.voice && (
              <div className="stack gap-2">
                <span className="label">Voice synthesis</span>
                <Choice selected={draft.voice_engine === "elevenlabs"} onSelect={() => set("voice_engine", "elevenlabs")} icon={<Mic />} title="ElevenLabs" badge="Natural · billed per character">
                  Falls back to gTTS automatically if ElevenLabs fails or the workspace's monthly character limit is reached.
                </Choice>
                <Choice selected={draft.voice_engine === "gtts"} onSelect={() => set("voice_engine", "gtts")} icon={<Mic />} title="Google TTS (gTTS)" badge="Free">
                  Robotic but free. Useful for long test sessions.
                </Choice>
              </div>
            )}
          </Section>

          <Section id="capabilities" title="Capabilities" text="What this agent can do, defined by its template. Every action runs only after the customer confirms a summary.">
            {t ? (
              <>
                <div className="cap-list">
                  {t.workflows.map((w) => (
                    <div className="cap" key={w.id}>
                      <div className="cap-icon"><CalendarCheck /></div>
                      <div className="stack gap-1" style={{ minWidth: 0 }}>
                        <span className="small strong">{w.action_label || w.description}</span>
                        <span className="xsmall subtle">{w.description}</span>
                        <span className="xsmall subtle">Collects: {w.slots.map((s) => s.name + (s.pii ? " (masked)" : "")).join(", ")}</span>
                      </div>
                    </div>
                  ))}
                  <div className="cap">
                    <div className="cap-icon"><BookOpen /></div>
                    <div className="stack gap-1">
                      <span className="small strong">Answer practical questions</span>
                      <span className="xsmall subtle">From this agent's knowledge base, with cited entries.</span>
                    </div>
                  </div>
                </div>
                <div className="grid-2">
                  <div className="cap" style={{ flexDirection: "column" }}>
                    <div className="row small strong"><ShieldCheck size={15} color="var(--good-text)" /> In scope</div>
                    <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>
                      {t.scope.allowed.map((s) => <li key={s}>{s}</li>)}
                    </ul>
                  </div>
                  <div className="cap" style={{ flexDirection: "column" }}>
                    <div className="row small strong"><ShieldAlert size={15} color="var(--warning-text)" /> Always transferred to a human</div>
                    <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>
                      {t.scope.forbidden.map((s) => <li key={s}>{s}</li>)}
                      <li>Explicit requests to speak to a person</li>
                    </ul>
                  </div>
                </div>
                <div className="row wrap small muted">
                  <Wrench size={14} /> Tools: {t.tools.map((x) => `${x.name} (${x.kind})`).join(", ")}
                  {t.safety_scripts > 0 && <Badge tone="warning">{t.safety_scripts} fixed safety scripts</Badge>}
                  {t.catalogue_items > 0 && <Badge>{t.catalogue_items} catalogue items</Badge>}
                </div>
                <div className="notice">
                  <Lock />
                  <span>Per-capability toggles and connections to external systems (your calendar, CRM, webhooks) are on the roadmap. Actions currently run on a simulated calendar dedicated to this agent.</span>
                </div>
              </>
            ) : (
              <Alert tone="warning">Template “{agent.template}” is not available on this server.</Alert>
            )}
          </Section>

          <Section id="knowledge" title="Knowledge base" text="Questions and answers the agent may use.">
            <div className="cap">
              <div className="cap-icon"><BookOpen /></div>
              <div className="grow">
                <div className="strong">{agent.knowledge_entries} entries</div>
                <div className="small muted">Private to this agent. Edits apply to the next conversation.</div>
              </div>
              <Link to="/app/knowledge" className="btn btn-secondary btn-sm">Manage</Link>
            </div>
          </Section>

          <Section id="danger" title="Delete agent" text="Removes the agent, its knowledge base and its calendar. Conversations stay in your history.">
            <div>
              <Button variant="danger" onClick={() => setConfirmDelete(true)}>Delete this agent</Button>
            </div>
          </Section>

          <div className="savebar">
            {dirty && <span className="small muted">Unsaved changes</span>}
            <Button variant="ghost" disabled={!dirty} onClick={() => setDraft(toDraft(agent))}>Discard</Button>
            <Button variant="primary" disabled={!dirty || !draft.name.trim() || !draft.greeting.trim()} loading={saving} onClick={save}>Save changes</Button>
          </div>
        </div>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title={`Delete “${agent.name}”?`}
        body="Its knowledge base and calendar are deleted permanently. Past conversations remain visible in your history."
        onClose={() => setConfirmDelete(false)}
        onConfirm={remove}
        loading={deleting}
      />
    </>
  );
}

function Section({ id, title, text, children }: { id: string; title: string; text: string; children: ReactNode }) {
  return (
    <section className="form-section" id={id}>
      <div>
        <h2>{title}</h2>
        <p>{text}</p>
      </div>
      <div className="form-grid">{children}</div>
    </section>
  );
}
function Choice({ selected, onSelect, icon, title, badge, children }: { selected: boolean; onSelect: () => void; icon: ReactNode; title: string; badge?: string; children: ReactNode }) {
  return (
    <label className={`option-card ${selected ? "selected" : ""}`}>
      <input type="radio" checked={selected} onChange={onSelect} />
      <div className="stack gap-1">
        <div className="row wrap">
          <span className="subtle" style={{ display: "inline-flex" }}>{icon}</span>
          <span className="strong">{title}</span>
          {badge && <Badge>{badge}</Badge>}
        </div>
        <span className="small muted">{children}</span>
      </div>
    </label>
  );
}
function ChannelRow({ icon, title, text, children }: { icon: ReactNode; title: string; text: string; children: ReactNode }) {
  return (
    <div className="cap" style={{ alignItems: "center" }}>
      <div className="cap-icon">{icon}</div>
      <div className="grow stack">
        <span className="small strong">{title}</span>
        <span className="xsmall subtle">{text}</span>
      </div>
      {children}
    </div>
  );
}

export function NoAgent() {
  return (
    <EmptyState icon={<Bot />} title="No agent yet" action={<Link to="/app/agent?new=1" className="btn btn-primary">Create an agent</Link>}>
      Create an agent from a template to use this page.
    </EmptyState>
  );
}
