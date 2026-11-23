import { Link } from "react-router-dom";
import {
  ArrowRight, AudioLines, BookOpenCheck, Brain, Building2, CalendarCheck, Car, Check, CheckCircle2, GraduationCap,
  Hotel, LineChart, Mic, ShieldCheck, ShoppingBag, Sparkles, Stethoscope, UserRound, Waypoints, Briefcase,
} from "lucide-react";
import { Badge } from "@/components/ui";
import { BRAND } from "@/brand";
import { useDocumentTitle } from "@/lib/hooks";

export function Home() {
  useDocumentTitle(`${BRAND.name} — AI agents that understand, answer and act`);
  return (
    <>
      {/* 1. hero */}
      <section className="hero">
        <div className="container">
          <div className="hero-copy">
            <span className="pill">
              <b>Agentic AI</b> For customer conversations that need an outcome
            </span>
            <h1>
              Your customers ask.
              <br />
              <span className="soft">Your agent</span> gets it done.
            </h1>
            <p className="hero-lead">
              {BRAND.name} deploys an AI agent that understands what callers and customers want, answers from your own
              knowledge base, and executes the operations you authorize — booking, rescheduling, cancelling — then hands
              off to your team whenever it should not decide alone.
            </p>
            <div className="hero-ctas">
              <Link to="/register" className="btn btn-primary btn-lg">
                Get started <ArrowRight />
              </Link>
              <Link to="/solutions" className="btn btn-secondary btn-lg">
                Explore solutions
              </Link>
            </div>
            <p className="hero-note">Voice and chat · Answers grounded in your data · Every action logged and reviewable</p>
          </div>
          <ProductPreview />
        </div>
      </section>

      {/* 2-3. overview / problem */}
      <section className="section alt">
        <div className="container split">
          <div>
            <div className="eyebrow">The problem</div>
            <h2 style={{ fontSize: "var(--fs-4xl)", letterSpacing: "-0.03em" }}>Most automated lines can route a call. Few can finish it.</h2>
            <p className="muted" style={{ fontSize: "var(--fs-lg)", marginTop: 16, lineHeight: 1.6 }}>
              Menu trees and FAQ bots recognise keywords. The moment a caller rephrases, mispronounces a word or asks
              two things at once, the request lands back on your staff — who then re-type it into the calendar or CRM.
            </p>
          </div>
          <div className="card card-pad">
            <div className="eyebrow">Our approach</div>
            <ul className="check-list" style={{ marginTop: 0 }}>
              <li><Check /><span><b>Understand the intent, not the keyword.</b> A language model reads every turn in context, including transcription errors ("ronds des vous" → "rendez-vous").</span></li>
              <li><Check /><span><b>Answer only from your data.</b> Replies to practical questions must cite entries of your knowledge base; unsupported answers are replaced by a hand-off offer.</span></li>
              <li><Check /><span><b>Act through verified tools.</b> The agent collects the details, the tool checks feasibility, the customer confirms, then the action runs.</span></li>
              <li><Check /><span><b>Stay inside the lines you draw.</b> Forbidden topics, safety scripts and explicit requests for a person go to a human, without the model deciding.</span></li>
            </ul>
          </div>
        </div>
      </section>

      {/* 4. capabilities */}
      <section className="section">
        <div className="container">
          <div className="section-head">
            <div className="eyebrow">Capabilities</div>
            <h2>One agent, from the first word to the executed action</h2>
            <p>Each capability is part of the running platform today, and each one is visible in your dashboard.</p>
          </div>
          <div className="features">
            <Feature icon={<Brain />} title="Contextual understanding">
              Intent, details and follow-ups are understood across the whole conversation, including relative dates
              ("next Tuesday at 10") and corrections.
            </Feature>
            <Feature icon={<BookOpenCheck />} title="Grounded answers">
              Practical questions are answered from your knowledge base, with the entries used recorded for every reply.
            </Feature>
            <Feature icon={<CalendarCheck />} title="Executed operations">
              Create, move or cancel appointments. Unavailable slots trigger alternatives instead of a dead end.
            </Feature>
            <Feature icon={<UserRound />} title="Human hand-off">
              A person is brought in on request, on sensitive topics, on repeated misunderstanding or on frustration.
            </Feature>
            <Feature icon={<AudioLines />} title="Voice and chat">
              Speech recognition tuned with your vocabulary, natural voice synthesis, and the same agent in a chat window.
            </Feature>
            <Feature icon={<LineChart />} title="Measured, not guessed">
              Conversations, actions, outcomes, latency, model tokens and voice characters — per workspace and per agent.
            </Feature>
          </div>
        </div>
      </section>

      {/* 5. how the agent works */}
      <section className="section alt">
        <div className="container">
          <div className="section-head center">
            <div className="eyebrow">How the agent works</div>
            <h2>Every turn follows the same accountable path</h2>
            <p>One language-model call per turn. Everything around it — checks, confirmations, actions — is deterministic.</p>
          </div>
          <div className="pipeline">
            <Pipe icon={<Mic />} title="Listen">Speech-to-text with a quality check; unusable audio is asked again.</Pipe>
            <Pipe icon={<Brain />} title="Understand">The LLM extracts intent and details, aware of the conversation so far.</Pipe>
            <Pipe icon={<BookOpenCheck />} title="Ground">Answers are written from your knowledge entries, which are cited and verified.</Pipe>
            <Pipe icon={<ShieldCheck />} title="Verify & act">Tools check feasibility, the customer confirms, then the operation executes.</Pipe>
            <Pipe icon={<AudioLines />} title="Respond">A short, natural reply, spoken or written, with the next question.</Pipe>
          </div>
          <div style={{ textAlign: "center", marginTop: 40 }}>
            <Link to="/how-it-works" className="btn btn-secondary">
              See the full setup process <ArrowRight />
            </Link>
          </div>
        </div>
      </section>

      {/* 6. domains */}
      <section className="section">
        <div className="container">
          <div className="section-head">
            <div className="eyebrow">Business domains</div>
            <h2>Configured per business, not hard-coded per industry</h2>
            <p>
              An agent is defined by its domain template, knowledge base, workflows and rules. The medical-imaging
              administration template ships today; the others show where the same engine applies.
            </p>
          </div>
          <div className="tiles">
            <Tile icon={<Stethoscope />} title="Healthcare administration" tag="Template available">Appointments and practical information. Never medical advice.</Tile>
            <Tile icon={<Hotel />} title="Hospitality">Reservations, changes, check-in questions.</Tile>
            <Tile icon={<Building2 />} title="Real estate">Viewing requests, listing information, lead qualification.</Tile>
            <Tile icon={<Car />} title="Automotive services">Service bookings, status questions, rescheduling.</Tile>
            <Tile icon={<ShoppingBag />} title="Retail & e-commerce">Order questions, returns policy, store information.</Tile>
            <Tile icon={<Briefcase />} title="Professional services">Consultation booking and intake questions.</Tile>
            <Tile icon={<GraduationCap />} title="Education & training">Enrolment information and session scheduling.</Tile>
            <Tile icon={<Waypoints />} title="Your business">Any team that answers the same requests every day.</Tile>
          </div>
        </div>
      </section>

      {/* 7. use cases */}
      <section className="section alt">
        <div className="container">
          <div className="section-head">
            <div className="eyebrow">Example interactions</div>
            <h2>What a conversation actually looks like</h2>
            <p>Taken from the medical-imaging template running on the platform (agent replies are in French, the template's language).</p>
          </div>
          <div className="grid-3">
            <UseCase title="Booking with an alternative" result={<Badge tone="good" icon={<CheckCircle2 />}>Appointment created</Badge>}>
              <div className="u">Je voudrais une écho du genou gauche mardi à 11 heures.</div>
              <div className="a">Ce créneau n'est pas possible. Je peux vous proposer mardi à 13 heures, 15 heures ou 17 heures. Lequel vous convient ?</div>
              <div className="u">La deuxième.</div>
            </UseCase>
            <UseCase title="A question answered from your data" result={<Badge tone="info">Source: FAQ entry F02</Badge>}>
              <div className="u">Vous êtes ouverts samedi vers midi ?</div>
              <div className="a">Oui, le samedi le centre est ouvert de 8 heures à 12 heures 30.</div>
            </UseCase>
            <UseCase title="Knowing when to step back" result={<Badge tone="warning" icon={<UserRound />}>Transferred to staff</Badge>}>
              <div className="u">Est-ce que c'est grave si j'ai mal au dos depuis l'examen ?</div>
              <div className="a">Je vous mets en relation avec une personne du secrétariat, merci de patienter.</div>
            </UseCase>
          </div>
        </div>
      </section>

      {/* 8. why */}
      <section className="section">
        <div className="container split">
          <div>
            <div className="eyebrow">Why {BRAND.name}</div>
            <h2 style={{ fontSize: "var(--fs-4xl)", letterSpacing: "-0.03em" }}>The model proposes. The system verifies.</h2>
            <p className="muted" style={{ fontSize: "var(--fs-lg)", marginTop: 16, lineHeight: 1.6 }}>
              Language models are good at understanding people and bad at being accountable. {BRAND.name} keeps them where they
              are strong and wraps every decision that matters in checks you can audit.
            </p>
            <Link to="/register" className="btn btn-primary" style={{ marginTop: 24 }}>
              Create your agent <ArrowRight />
            </Link>
          </div>
          <ul className="check-list">
            <li><ShieldCheck /><span><b>No action without confirmation.</b> The customer hears a summary and says yes before anything is written.</span></li>
            <li><ShieldCheck /><span><b>No invented facts.</b> Cited sources are checked against the entries actually provided.</span></li>
            <li><ShieldCheck /><span><b>Personal data masked.</b> Names and phone numbers are redacted before conversations are stored.</span></li>
            <li><ShieldCheck /><span><b>Keys stay on the server.</b> The browser never sees a model or voice API key.</span></li>
            <li><ShieldCheck /><span><b>Provider-agnostic.</b> Any OpenAI-compatible model endpoint, with automatic fallback models.</span></li>
            <li><ShieldCheck /><span><b>Isolated workspaces.</b> Each business has its own agents, knowledge, calendar and history.</span></li>
          </ul>
        </div>
      </section>

      {/* 9. CTA */}
      <section className="section-sm">
        <div className="container">
          <div className="cta-band">
            <Sparkles size={22} style={{ margin: "0 auto 16px", opacity: 0.7 }} />
            <h2>Test an agent on your own requests</h2>
            <p>Create a workspace, pick a template, load your knowledge base and talk to your agent in the Playground — by text or by voice.</p>
            <div className="hero-ctas">
              <Link to="/register" className="btn btn-primary btn-lg">
                Get started
              </Link>
              <Link to="/contact" className="btn btn-secondary btn-lg">
                Request a demo
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

function Feature({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="feature">
      <div className="f-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function Pipe({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="pipe-step">
      <div className="pipe-icon">{icon}</div>
      <div>
        <h4>{title}</h4>
        <p>{children}</p>
      </div>
    </div>
  );
}
function Tile({ icon, title, tag, children }: { icon: React.ReactNode; title: string; tag?: string; children: React.ReactNode }) {
  return (
    <div className="tile">
      <div className="row-between">
        <div className="f-icon">{icon}</div>
        {tag && <Badge tone="accent">{tag}</Badge>}
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function UseCase({ title, result, children }: { title: string; result: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="usecase">
      <h3>{title}</h3>
      <div className="exchange">{children}</div>
      <div>{result}</div>
    </div>
  );
}

/** Illustration built from the real Playground components' visual language. Not live data. */
function ProductPreview() {
  return (
    <div>
      <div className="preview" aria-label="Illustration of the Playground">
        <div className="preview-bar">
          <i />
          <i />
          <i />
          <span>Playground · Reception agent · voice</span>
        </div>
        <div className="preview-grid">
          <div className="preview-chat">
            <div className="msg agent">
              <div className="msg-avatar"><Brain size={15} /></div>
              <div className="msg-body"><div className="bubble">Centre d'imagerie, bonjour. Que puis-je faire pour vous ?</div></div>
            </div>
            <div className="msg user">
              <div className="msg-avatar"><UserRound size={15} /></div>
              <div className="msg-body">
                <div className="bubble">Je voudrais prendre un ronds des vous pour une écho du genou gauche, jeudi matin.</div>
                <div className="msg-meta">transcribed by speech-to-text</div>
              </div>
            </div>
            <div className="msg agent">
              <div className="msg-avatar"><Brain size={15} /></div>
              <div className="msg-body">
                <div className="bubble">Très bien, une échographie du genou gauche jeudi matin. À quel nom dois-je enregistrer le rendez-vous ?</div>
                <div className="msg-meta">
                  <Badge tone="accent">LLM · new appointment</Badge>
                  <span>asks for: name</span>
                </div>
              </div>
            </div>
          </div>
          <div className="preview-side">
            <div>
              <div className="xsmall subtle" style={{ marginBottom: 8 }}>WHAT THE AGENT UNDERSTOOD</div>
              <div className="stack gap-2">
                <div className="step-chip done"><span className="n"><Check size={12} /></span>Exam · Ultrasound, left knee</div>
                <div className="step-chip done"><span className="n"><Check size={12} /></span>Slot · Thursday 09:00</div>
                <div className="step-chip"><span className="n">3</span>Name</div>
                <div className="step-chip"><span className="n">4</span>Phone</div>
              </div>
            </div>
            <div className="card" style={{ padding: 14 }}>
              <div className="row-between">
                <span className="small strong">Next action</span>
                <Badge tone="info">Pending</Badge>
              </div>
              <div className="small muted" style={{ marginTop: 6 }}>Create appointment · calendar.book</div>
              <div className="xsmall subtle" style={{ marginTop: 4 }}>Runs only after the caller confirms the summary.</div>
            </div>
          </div>
        </div>
      </div>
      <p className="preview-caption">Illustration of the Playground based on a real test exchange; not live data.</p>
    </div>
  );
}
