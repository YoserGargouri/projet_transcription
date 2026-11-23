import { Link } from "react-router-dom";
import { ArrowRight, Briefcase, Building2, Car, GraduationCap, Hotel, Info, ShoppingBag, Stethoscope, Waypoints } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui";
import { BRAND } from "@/brand";
import { useDocumentTitle } from "@/lib/hooks";

const INDUSTRIES: { icon: ReactNode; title: string; text: string; requests: string[]; boundary?: string; available?: boolean }[] = [
  { icon: <Stethoscope />, title: "Healthcare administration", available: true,
    text: "Appointment booking, rescheduling and cancellation for imaging centres and clinics, plus practical information.",
    requests: ["Book an exam from a prescription", "Opening hours and access", "What to bring, how to prepare"],
    boundary: "Administrative only: questions about symptoms, results or the choice of an exam are always transferred to staff." },
  { icon: <Hotel />, title: "Hospitality and hotels", text: "Reservations and changes, arrival information and amenities.", requests: ["Change a reservation date", "Late check-in", "Parking and breakfast hours"] },
  { icon: <Building2 />, title: "Real estate", text: "Viewing requests and qualification of incoming leads before an agent calls back.", requests: ["Book a viewing", "Is this listing still available?", "Budget and area qualification"] },
  { icon: <Car />, title: "Automotive services", text: "Service and repair appointments, and questions about opening hours or loan vehicles.", requests: ["Book a service", "Reschedule a drop-off", "Is a courtesy car available?"] },
  { icon: <ShoppingBag />, title: "Retail and e-commerce", text: "Store information and policy questions answered from your own documentation.", requests: ["Returns policy", "Store opening hours", "Click-and-collect information"] },
  { icon: <Briefcase />, title: "Professional services", text: "Consultation booking and first-contact intake for firms and practices.", requests: ["Book a first consultation", "Documents to prepare", "Fees and availability"] },
  { icon: <GraduationCap />, title: "Education and training centres", text: "Enrolment questions and session scheduling.", requests: ["Next session dates", "Enrolment requirements", "Change of session"] },
  { icon: <Waypoints />, title: "Other businesses", text: "Any team that answers the same requests every day and records the result somewhere.", requests: ["Repeated questions", "Bookings and changes", "Hand-off to the right person"] },
];

export function Industries() {
  useDocumentTitle(`Industries — ${BRAND.name}`);
  return (
    <>
      <section className="page-hero">
        <div className="container">
          <div className="eyebrow">Industries & use cases</div>
          <h1>Where a configurable agent fits</h1>
          <p>The engine is domain-agnostic: an industry is a template plus your own knowledge and rules.</p>
        </div>
      </section>
      <section className="section-sm">
        <div className="container">
          <div className="notice" style={{ marginBottom: 32 }}>
            <Info />
            <span>
              Only the healthcare-administration template is available today. The other industries are potential
              applications of the same engine, not existing integrations or customers.
            </span>
          </div>
          <div className="grid-2">
            {INDUSTRIES.map((i) => (
              <div className="usecase" key={i.title}>
                <div className="row-between">
                  <div className="f-icon">{i.icon}</div>
                  <Badge tone={i.available ? "good" : "neutral"}>{i.available ? "Template available" : "Potential application"}</Badge>
                </div>
                <h3>{i.title}</h3>
                <p className="muted">{i.text}</p>
                <ul className="check-list" style={{ marginTop: 0 }}>
                  {i.requests.map((r) => (
                    <li key={r}>
                      <ArrowRight />
                      <span>{r}</span>
                    </li>
                  ))}
                </ul>
                {i.boundary && <div className="alert alert-warning">{i.boundary}</div>}
              </div>
            ))}
          </div>
          <div className="row wrap" style={{ marginTop: 40 }}>
            <Link to="/contact" className="btn btn-primary">
              Discuss your use case <ArrowRight />
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
