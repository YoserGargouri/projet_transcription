import { useState, type FormEvent } from "react";
import { CheckCircle2, Mail, MapPin, Phone } from "lucide-react";
import { api } from "@/api/client";
import { Alert, Button, Card, Field } from "@/components/ui";
import { BRAND } from "@/brand";
import { useDocumentTitle } from "@/lib/hooks";

const DOMAINS = ["Healthcare administration", "Hospitality", "Real estate", "Automotive services", "Retail & e-commerce", "Professional services", "Education & training", "Other"];

export function Contact() {
  useDocumentTitle(`Contact — ${BRAND.name}`);
  const [form, setForm] = useState({ name: "", business_name: "", email: "", business_domain: "", message: "" });
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setState("sending");
    try {
      await api.post("/public/demo-requests", form);
      setState("sent");
    } catch (err) {
      setError((err as Error).message);
      setState("idle");
    }
  };

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <div className="eyebrow">Contact</div>
          <h1>Request a demo</h1>
          <p>Tell us about your business and the requests you receive most often. We'll set up a walkthrough with an agent configured for them.</p>
        </div>
      </section>
      <section className="section-sm">
        <div className="container split" style={{ alignItems: "start" }}>
          <Card>
            <div className="card-body" style={{ padding: 28 }}>
              {state === "sent" ? (
                <div className="empty" style={{ padding: "32px 0" }}>
                  <div className="empty-icon" style={{ color: "var(--good-text)" }}>
                    <CheckCircle2 />
                  </div>
                  <h3>Request received</h3>
                  <p>Thank you. Your request has been recorded and we will get back to you at the address you provided.</p>
                </div>
              ) : (
                <form className="form-grid" onSubmit={submit} noValidate={false}>
                  <div className="grid-2">
                    <Field label="Your name" htmlFor="c-name">
                      <input id="c-name" className="input" required maxLength={80} value={form.name} onChange={set("name")} autoComplete="name" />
                    </Field>
                    <Field label="Business name" htmlFor="c-biz">
                      <input id="c-biz" className="input" required maxLength={120} value={form.business_name} onChange={set("business_name")} autoComplete="organization" />
                    </Field>
                  </div>
                  <Field label="Business email" htmlFor="c-email">
                    <input id="c-email" type="email" className="input" required value={form.email} onChange={set("email")} autoComplete="email" />
                  </Field>
                  <Field label="Business domain" htmlFor="c-domain">
                    <select id="c-domain" className="select" value={form.business_domain} onChange={set("business_domain")}>
                      <option value="">Select…</option>
                      {DOMAINS.map((d) => (
                        <option key={d}>{d}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Your requirements" htmlFor="c-msg" hint="Which requests should the agent handle? Which channels? Any systems to connect?">
                    <textarea id="c-msg" className="textarea" rows={5} maxLength={4000} value={form.message} onChange={set("message")} />
                  </Field>
                  {error && <Alert tone="critical">{error}</Alert>}
                  <Button variant="primary" type="submit" loading={state === "sending"} size="lg">
                    Send request
                  </Button>
                </form>
              )}
            </div>
          </Card>
          <div className="stack gap-4">
            <h2 style={{ fontSize: "var(--fs-xl)" }}>Other ways to reach us</h2>
            <p className="muted">Contact details will be published here. The fields below are placeholders.</p>
            <div className="stack gap-3">
              <div className="row muted"><Mail size={16} /> {BRAND.contactEmail}</div>
              <div className="row muted"><Phone size={16} /> Phone number — to be announced</div>
              <div className="row muted"><MapPin size={16} /> Address — to be announced</div>
            </div>
            <Alert tone="info">Requests sent with this form are stored in the platform database. Email notifications are not configured yet.</Alert>
          </div>
        </div>
      </section>
    </>
  );
}
