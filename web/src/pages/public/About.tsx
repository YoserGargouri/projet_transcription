import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { BRAND } from "@/brand";
import { useDocumentTitle } from "@/lib/hooks";

export function About() {
  useDocumentTitle(`About — ${BRAND.name}`);
  return (
    <>
      <section className="page-hero">
        <div className="container">
          <div className="eyebrow">About</div>
          <h1>Making routine customer requests finish themselves</h1>
          <p>
            {BRAND.name} started from a concrete problem: a call centre where most calls ask for the same few things, yet
            every one of them still needs a person to understand it and type it somewhere.
          </p>
        </div>
      </section>
      <section className="section-sm">
        <div className="container">
          <div className="prose">
            <h2>The problem we are addressing</h2>
            <p>
              Businesses that take appointments or answer practical questions receive a large volume of repetitive
              requests: book, move, cancel, "what time do you open", "what should I bring". Classic automation handles
              them poorly. Phone menus force callers through trees; keyword bots fail as soon as someone rephrases or a
              word is misheard; and when they do succeed, the actual operation still waits for a human.
            </p>
            <h2>Our approach to agentic AI</h2>
            <p>
              We treat the language model as the part of the system that understands people — what they want, the
              details they gave, what they meant despite an imperfect transcription — and we keep everything that must
              be reliable outside of it. Answers have to come from the business's own knowledge and cite it. Actions go
              through tools that verify feasibility, are read back to the customer and run only after confirmation.
              Topics the agent must not handle, such as medical advice in a healthcare setting, are routed to a person
              by rules rather than by the model's judgement.
            </p>
            <p>
              The same engine is configured per business: a domain template describes intents, workflows, tools and
              guard-rails; each business then brings its own knowledge base, persona and settings. Nothing about one
              industry is hard-coded into the engine.
            </p>
            <h2>What we aim for</h2>
            <p>
              Customers who get an answer or a confirmed booking at any hour, staff who spend their time on the
              conversations that genuinely need them, and managers who can see exactly what the agent did and why —
              every conversation, every action, every model call accounted for.
            </p>
            <h2>Where the project stands</h2>
            <p>
              {BRAND.name} is a working prototype. It runs real conversations by text and voice, executes operations on a
              simulated calendar, and reports what happened in the dashboard. Integrations such as telephony and external
              calendars are on the roadmap, and we label them as such throughout the product.
            </p>
          </div>
          <div style={{ marginTop: 48 }} className="row wrap">
            <Link to="/how-it-works" className="btn btn-secondary">
              How it works <ArrowRight />
            </Link>
            <Link to="/contact" className="btn btn-ghost">
              Talk to us
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
