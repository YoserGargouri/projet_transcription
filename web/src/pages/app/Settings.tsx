import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AudioLines, Bot, Brain, Globe, Mail, MessageSquareText, Mic, Monitor, Moon, Phone, Plug, Sun, Webhook } from "lucide-react";
import { api } from "@/api/client";
import type { Integrations } from "@/api/types";
import { Alert, Badge, Button, ErrorState, Field, PageHeader, Segmented, Skeleton } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { num } from "@/lib/format";
import { useAsync, useDocumentTitle } from "@/lib/hooks";
import { useTheme, useToast } from "@/lib/ui-state";

export function SettingsPage() {
  useDocumentTitle("Settings");
  const { me, refresh } = useAuth();
  const toast = useToast();
  const [theme, setTheme] = useTheme();
  const integ = useAsync((s) => api.get<Integrations>("/integrations", s), []);
  const ws = me!.workspace;

  const [biz, setBiz] = useState({ name: ws.name, business_type: ws.business_type });
  const [profile, setProfile] = useState(me!.user.name);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [limit, setLimit] = useState(String(ws.settings.tts_monthly_char_limit ?? ""));
  const [pricing, setPricing] = useState({
    currency: ws.settings.pricing.currency || "USD",
    llm_input_per_million: ws.settings.pricing.llm_input_per_million ?? "",
    llm_output_per_million: ws.settings.pricing.llm_output_per_million ?? "",
    tts_per_thousand_chars: ws.settings.pricing.tts_per_thousand_chars ?? "",
  });
  const [saving, setSaving] = useState<string | null>(null);
  useEffect(() => {
    if (window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView();
  }, []);

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setSaving(key);
    try {
      await fn();
      await refresh();
      toast(ok);
      return true;
    } catch (e) {
      toast((e as Error).message, "critical");
      return false;
    } finally {
      setSaving(null);
    }
  };
  const numOrNull = (v: string | number) => (v === "" ? null : Number(v));
  const i = integ.data;

  return (
    <>
      <PageHeader title="Settings" sub="Workspace, account, integrations and usage limits." />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Sections">
          <a href="#business">Business profile</a>
          <a href="#account">Account</a>
          <a href="#preferences">Preferences</a>
          <a href="#integrations">API integrations</a>
          <a href="#channels">Channels</a>
          <a href="#usage">Usage & limits</a>
        </nav>
        <div>
          <Section id="business" title="Business profile" text="Your workspace. Agents, knowledge and conversations belong to it and are isolated from other workspaces.">
            <Field label="Business name" htmlFor="s-biz">
              <input id="s-biz" className="input" maxLength={120} value={biz.name} onChange={(e) => setBiz({ ...biz, name: e.target.value })} />
            </Field>
            <Field label="Business type" htmlFor="s-type">
              <input id="s-type" className="input" maxLength={120} value={biz.business_type} onChange={(e) => setBiz({ ...biz, business_type: e.target.value })} />
            </Field>
            <div>
              <Button variant="primary" loading={saving === "biz"} disabled={!biz.name.trim()} onClick={() => run("biz", () => api.patch("/workspace", biz), "Business profile saved")}>Save</Button>
            </div>
          </Section>

          <Section id="account" title="Account" text="Your personal details and password.">
            <Field label="Name" htmlFor="s-name">
              <input id="s-name" className="input" maxLength={80} value={profile} onChange={(e) => setProfile(e.target.value)} />
            </Field>
            <Field label="Email" htmlFor="s-email" hint="Changing the login email is not available yet.">
              <input id="s-email" className="input" value={me!.user.email} disabled />
            </Field>
            <div>
              <Button loading={saving === "me"} disabled={!profile.trim()} onClick={() => run("me", () => api.patch("/auth/me", { name: profile }), "Profile saved")}>Save name</Button>
            </div>
            <hr className="divider" style={{ margin: "8px 0" }} />
            <div className="grid-2">
              <Field label="Current password" htmlFor="s-pw1">
                <input id="s-pw1" type="password" className="input" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
              </Field>
              <Field label="New password" htmlFor="s-pw2" hint="At least 8 characters. Other sessions are signed out.">
                <input id="s-pw2" type="password" className="input" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
              </Field>
            </div>
            <div>
              <Button
                loading={saving === "pw"}
                disabled={!pw.current_password || pw.new_password.length < 8}
                onClick={async () => (await run("pw", () => api.post("/auth/password", pw), "Password changed")) && setPw({ current_password: "", new_password: "" })}
              >
                Change password
              </Button>
            </div>
          </Section>

          <Section id="preferences" title="Preferences" text="Interface appearance and language. Agent behaviour is configured per agent.">
            <Field label="Theme" htmlFor="s-theme">
              <Segmented label="Theme" value={theme} onChange={setTheme} options={[{ value: "system", label: "System", icon: <Monitor /> }, { value: "light", label: "Light", icon: <Sun /> }, { value: "dark", label: "Dark", icon: <Moon /> }]} />
            </Field>
            <Field label="Interface language" htmlFor="s-lang" hint="Agents speak the language of their template (French for the medical-imaging template).">
              <div className="row"><Globe size={16} className="subtle" /> English <Badge>More languages: roadmap</Badge></div>
            </Field>
            <Field label="Agent preferences" htmlFor="s-agent">
              <Link to="/app/agent" className="btn btn-secondary" style={{ alignSelf: "flex-start" }}><Bot /> Open the AI Agent page</Link>
            </Field>
          </Section>

          <Section id="integrations" title="API integrations" text="Configured on the server through environment variables. Keys never reach the browser; this page only shows whether each service is set up.">
            {integ.error ? (
              <ErrorState error={integ.error} onRetry={integ.reload} />
            ) : !i ? (
              <Skeleton h={220} />
            ) : (
              <div className="stack gap-3">
                <Integration icon={<Brain />} title="Language model" status={i.llm.configured}>
                  {i.llm.configured ? (
                    <>
                      {i.llm.provider} · <span className="mono">{i.llm.model}</span>
                      {i.llm.fallback_models.length > 0 && <> · fallbacks: <span className="mono">{i.llm.fallback_models.join(", ")}</span></>}
                      {i.llm.timeout_s && <> · budget {i.llm.timeout_s}s per call</>}
                    </>
                  ) : (
                    "Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in the server's .env. Without it, agents run on rules only."
                  )}
                </Integration>
                <Integration icon={<AudioLines />} title="ElevenLabs voice" status={i.elevenlabs.configured}>
                  {i.elevenlabs.configured ? (
                    <>Model <span className="mono">{i.elevenlabs.model || "default"}</span> · {i.elevenlabs.voice_configured ? "voice set" : "first voice of the account"} · {num(i.elevenlabs.chars_this_month)} characters this month</>
                  ) : (
                    "Set ELEVENLABS_API_KEY in the server's .env. Voice falls back to gTTS."
                  )}
                </Integration>
                <Integration icon={<Mic />} title="Speech-to-text" status={true}>
                  Local engines: {i.stt.engines.join(", ")}. Chosen per template.
                </Integration>
                <Integration icon={<Mail />} title="Email delivery" status={i.email.configured} roadmap={!i.email.configured}>
                  {i.email.configured ? "Development mode: password-reset links are printed in the server console." : "Not configured: password-reset emails and demo-request notifications are not sent."}
                </Integration>
                <Integration icon={<Phone />} title="Telephony (SIP / phone numbers)" status={false} roadmap>
                  Receiving real phone calls requires a telephony provider integration.
                </Integration>
                <Integration icon={<Webhook />} title="Calendars, CRM, webhooks" status={false} roadmap>
                  Actions currently run on a simulated calendar per agent.
                </Integration>
              </div>
            )}
          </Section>

          <Section id="channels" title="Communication channels" text="Channels supported by the platform. Enable or disable them per agent on the AI Agent page.">
            <div className="stack gap-3">
              <Integration icon={<MessageSquareText />} title="Web chat" status={true}>Available in the Playground.</Integration>
              <Integration icon={<Mic />} title="Voice (browser microphone)" status={true}>Available in the Playground for templates with a voice channel.</Integration>
              <Integration icon={<Plug />} title="Website widget" status={false} roadmap>Embeddable chat for your website.</Integration>
              <Integration icon={<Phone />} title="Phone line" status={false} roadmap>Inbound calls on a dedicated number.</Integration>
            </div>
          </Section>

          <Section id="usage" title="Usage & limits" text="Protect your API budgets and estimate costs.">
            <Field label="ElevenLabs monthly character limit" htmlFor="s-limit" hint={`Above it, voice replies switch to free gTTS automatically. 0 = no limit.${i ? ` Used this month: ${num(i.elevenlabs.chars_this_month)}.` : ""}`}>
              <input id="s-limit" type="number" min={0} className="input" style={{ maxWidth: 220 }} value={limit} onChange={(e) => setLimit(e.target.value)} />
            </Field>
            <div className="stack gap-2">
              <span className="label">Unit prices for cost estimates</span>
              <span className="hint">Leave empty to not estimate costs (e.g. free tiers). Values are your provider's public prices.</span>
              <div className="grid-2">
                <Field label="LLM input, per 1M tokens" htmlFor="s-p1">
                  <input id="s-p1" type="number" min={0} step="any" className="input" value={pricing.llm_input_per_million} onChange={(e) => setPricing({ ...pricing, llm_input_per_million: e.target.value })} />
                </Field>
                <Field label="LLM output, per 1M tokens" htmlFor="s-p2">
                  <input id="s-p2" type="number" min={0} step="any" className="input" value={pricing.llm_output_per_million} onChange={(e) => setPricing({ ...pricing, llm_output_per_million: e.target.value })} />
                </Field>
                <Field label="Voice, per 1,000 characters" htmlFor="s-p3">
                  <input id="s-p3" type="number" min={0} step="any" className="input" value={pricing.tts_per_thousand_chars} onChange={(e) => setPricing({ ...pricing, tts_per_thousand_chars: e.target.value })} />
                </Field>
                <Field label="Currency" htmlFor="s-cur">
                  <select id="s-cur" className="select" value={pricing.currency} onChange={(e) => setPricing({ ...pricing, currency: e.target.value })}>
                    {["USD", "EUR", "TND", "GBP"].map((c) => <option key={c}>{c}</option>)}
                  </select>
                </Field>
              </div>
            </div>
            <Alert tone="info">Per-call limits for the language model (LLM_MAX_CALLS, LLM_MAX_TOKENS, LLM_TIMEOUT_S) are set in the server environment.</Alert>
            <div>
              <Button
                variant="primary"
                loading={saving === "usage"}
                onClick={() =>
                  run("usage", () => api.patch("/workspace", {
                    settings: {
                      tts_monthly_char_limit: limit === "" ? 0 : Number(limit),
                      pricing: { currency: pricing.currency, llm_input_per_million: numOrNull(pricing.llm_input_per_million), llm_output_per_million: numOrNull(pricing.llm_output_per_million), tts_per_thousand_chars: numOrNull(pricing.tts_per_thousand_chars) },
                    },
                  }), "Usage settings saved")
                }
              >
                Save usage settings
              </Button>
            </div>
          </Section>
        </div>
      </div>
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

function Integration({ icon, title, status, roadmap, children }: { icon: ReactNode; title: string; status: boolean; roadmap?: boolean; children: ReactNode }) {
  return (
    <div className="cap" style={{ alignItems: "center" }}>
      <div className="cap-icon">{icon}</div>
      <div className="grow stack gap-1" style={{ minWidth: 0 }}>
        <span className="small strong">{title}</span>
        <span className="xsmall subtle" style={{ overflowWrap: "anywhere" }}>{children}</span>
      </div>
      {status ? <Badge tone="good"><span className="dot" />Connected</Badge> : roadmap ? <Badge>Roadmap</Badge> : <Badge tone="warning">Not configured</Badge>}
    </div>
  );
}
