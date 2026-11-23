import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { EmptyState } from "@/components/ui";

export function NotFound() {
  return (
    <div className="container section">
      <EmptyState icon={<Compass />} title="Page not found" action={<Link to="/" className="btn btn-secondary">Back to home</Link>}>
        The page you are looking for does not exist or has moved.
      </EmptyState>
    </div>
  );
}
