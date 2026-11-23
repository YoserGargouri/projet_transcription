import { Link } from "react-router-dom";
import {
  ArrowRight, BookOpenCheck, Bot, Brain, CalendarCheck, Filter, PhoneIncoming, Workflow, MessagesSquare,
} from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui";
import { BRAND } from "@/brand";
import { useDocumentTitle } from "@/lib/hooks";

interface Sol {
  icon: ReactNode;
  title: string;
  text: string;
  status: "available" | "roadmap";
  example: { u: string; a: string; result: string };
}

const SOLUTIONS: Sol[] = [
  {
    icon: <PhoneIncoming />, title: "AI-powered inbound call handling", status: "available",
    text: "Speech is transcribed with a quality check and your business vocabulary, understood in context, and answered with a natural voice. Inaudible audio is asked again; repeated failures reach a person.",
    example: { u: "(voice) I'd like to move my appointment to Friday afternoon.", a: "Of course. What is your appointment reference?", result: "Voice turn · speech-to-text → LLM → synthesized reply" },
  },
  {
    icon: <MessagesSquare />, title: "Intelligent customer support", status: "available",
    text: "The same agent answers in a chat window. It keeps the thread of the conversation, so a side question in the middle of a booking is answered and the booking resumes.",
    example: { u: "Before we continue — is the centre wheelchair accessible?", a: "Yes, the centre is accessible. Which day would suit you?", result: "Answer + workflow resumed" },
  },
  {
    icon: <CalendarCheck />, title: "Appointment and reservation management", status: "available",
    text: "Create, reschedule, cancel and look up appointments. The calendar tool checks the slot before the summary; if it is taken, closed or past, the agent proposes alternatives.",
    example: { u: "Tuesday at 11, please.", a: "That slot isn't available. I can offer 1 pm, 3 pm or 5 pm.", result: "Availability checked · alternatives offered" },
  },
  {
    icon: <Filter />, title: "Customer request qualification", status: "available",
    text: "Each turn is classified into one of your intents with the details extracted. Ambiguous requests trigger a clarification question instead of a guess.",
    example: { u: "An MRI of the knee.", a: "Does your prescription say left or right?", result: "Clarification · item never guessed" },
  },
  {
    icon: <BookOpenCheck />, title: "Business information retrieval", status: "available",
    text: "Answers are written from your knowledge base and must cite the entries used. If nothing supports an answer, the agent says so and offers a person.",
    example: { u: "Do you take cards?", a: "Yes, we accept cards and cash at the front desk.", result: "Grounded · source cited" },
  },
  {
    icon: <Workflow />, title: "Automated workflow execution", status: "available",
    text: "Workflows define the information to collect, how to validate it, the summary to read back and the tool to call. Every execution is logged with its status and duration.",
    example: { u: "Yes, that's correct.", a: "Done, your reference is RDV-7KQ4ZA.", result: "Action executed · logged" },
  },
  {
    icon: <Brain />, title: "Context-aware conversational AI", status: "available",
    text: "Relative dates, corrections and follow-ups are resolved against the conversation and today's date. The model writes its reasoning summary before the reply, which keeps answers consistent.",
    example: { u: "Actually, make it the day after.", a: "Noted, Wednesday at 10 am instead.", result: "Slot updated from context" },
  },
  {
    icon: <Bot />, title: "Business-specific AI agents", status: "available",
    text: "Each agent combines a domain template with its own name, greeting, tone, knowledge base, calendar and voice. Generating a full configuration from a free-text business description is on the roadmap.",
    example: { u: "(configuration) Persona, greeting, style, knowledge, voice", a: "Agent ready to test in the Playground", result: "Configured per workspace" },
  },
];

export function Solutions() {
  useDocumentTitle(`Solutions — ${BRAND.name}`);
  return (
    <>
      <section className="page-hero">
        <div className="container">
          <div className="eyebrow">Solutions</div>
          <h1>Capabilities that end in a resolved request</h1>
          <p>Every solution below runs on the same agent engine. Examples are translated and simplified from conversations with the medical-imaging template.</p>
        </div>
      </section>
      <section className="section-sm">
        <div className="container">
          {SOLUTIONS.map((s) => (
            <div className="sol" key={s.title}>
              <div>
                <div className="row">
                  <div className="f-icon">{s.icon}</div>
                  <Badge tone={s.status === "available" ? "good" : "neutral"}>{s.status === "available" ? "Available" : "Roadmap"}</Badge>
                </div>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </div>
              <div className="usecase">
                <div className="xsmall subtle">EXAMPLE</div>
                <div className="exchange">
                  <div className="u">{s.example.u}</div>
                  <div className="a">{s.example.a}</div>
                </div>
                <div>
                  <Badge tone="accent">{s.example.result}</Badge>
                </div>
              </div>
            </div>
          ))}
          <div className="row wrap" style={{ marginTop: 32 }}>
            <Link to="/register" className="btn btn-primary">
              Get started <ArrowRight />
            </Link>
            <Link to="/industries" className="btn btn-secondary">
              See industries
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
