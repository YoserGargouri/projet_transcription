import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui";
import { BRAND } from "@/brand";
import { useDocumentTitle } from "@/lib/hooks";

const STEPS: { title: string; text: string; who: "You" | "Platform" | "Customer" | "Agent"; status?: string }[] = [
  { who: "You", title: "Create an account", text: "Register and get a private workspace. Everything you create — agents, knowledge, conversations — is isolated to it on the server." },
  { who: "You", title: "Define your domain and business type", text: "Describe what your business does and pick the domain template closest to it. The template brings intents, workflows, tools and guard-rails." },
  { who: "You", title: "Configure your AI agent", text: "Name it, write its greeting and tone, choose the understanding mode, the voice and the channels it should serve." },
  { who: "You", title: "Provide your knowledge base and datasets", text: "Edit the questions and answers the agent may use, add your own entries or import them from a CSV file." },
  { who: "Platform", title: "The agent is assembled for your business", text: "Your settings, knowledge and a dedicated calendar are combined with the template. Generating this configuration from a free-text description is planned.", status: "Partly automated" },
  { who: "Customer", title: "Customers reach the agent", text: "By chat or by voice in the Playground today. Telephone numbers and website widgets are on the roadmap.", status: "Phone: roadmap" },
  { who: "Agent", title: "The LLM understands and decides the next step", text: "One model call per turn returns the intent, the extracted details, the knowledge entries used and a natural reply. Rules provide hints and a fallback." },
  { who: "Agent", title: "Authorized operations are executed", text: "Tools verify feasibility first; the customer confirms a summary; then the action runs and its result is read back." },
  { who: "You", title: "Monitor interactions, actions and performance", text: "Review transcripts, executed actions, outcomes, latency and usage in your dashboard, and adjust the agent." },
];

export function HowItWorks() {
  useDocumentTitle(`How it works — ${BRAND.name}`);
  return (
    <>
      <section className="page-hero">
        <div className="container">
          <div className="eyebrow">How it works</div>
          <h1>From sign-up to a monitored agent in nine steps</h1>
          <p>What you configure, what the platform does for you, and what happens when a customer starts a conversation.</p>
        </div>
      </section>
      <section className="section-sm">
        <div className="container">
          <div className="process">
            {STEPS.map((s, i) => (
              <div className="proc" key={s.title}>
                <div className="proc-rail">
                  <div className="proc-num">{i + 1}</div>
                  <div className="proc-line" />
                </div>
                <div className="proc-body">
                  <div className="row">
                    <Badge tone={s.who === "You" ? "neutral" : s.who === "Agent" ? "accent" : s.who === "Customer" ? "info" : "outline"}>{s.who}</Badge>
                    {s.status && <Badge tone="warning">{s.status}</Badge>}
                  </div>
                  <h3>{s.title}</h3>
                  <p>{s.text}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="cta-band" style={{ marginTop: 32 }}>
            <h2>Try the loop yourself</h2>
            <p>Steps 1 to 4 take a few minutes. Then open the Playground and talk to your agent.</p>
            <div className="hero-ctas">
              <Link to="/register" className="btn btn-primary btn-lg">
                Create a workspace <ArrowRight />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
