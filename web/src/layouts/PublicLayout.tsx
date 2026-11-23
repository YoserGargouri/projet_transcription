import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { Button, Logo } from "@/components/ui";
import { BRAND } from "@/brand";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { to: "/solutions", label: "Solutions" },
  { to: "/how-it-works", label: "How it works" },
  { to: "/industries", label: "Industries" },
  { to: "/about", label: "About" },
  { to: "/contact", label: "Contact" },
];

export function PublicLayout() {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => {
    setOpen(false);
    window.scrollTo(0, 0);
  }, [loc.pathname]);

  return (
    <>
      <header className="pub-nav">
        <div className="container">
          <Link to="/" aria-label={`${BRAND.name} home`}>
            <Logo />
          </Link>
          <nav className="pub-links" aria-label="Main">
            {LINKS.map((l) => (
              <NavLink key={l.to} to={l.to} className={({ isActive }) => (isActive ? "active" : "")}>
                {l.label}
              </NavLink>
            ))}
          </nav>
          <div className="pub-cta">
            {me ? (
              <Link to="/app" className="btn btn-primary btn-sm">
                Open app
              </Link>
            ) : (
              <>
                <Link to="/login" className="btn btn-ghost btn-sm">
                  Log in
                </Link>
                <Link to="/register" className="btn btn-primary btn-sm">
                  Get started
                </Link>
              </>
            )}
            <Button variant="ghost" size="sm" className="pub-burger" icon={open ? <X /> : <Menu />} onClick={() => setOpen((v) => !v)} aria-label="Menu" aria-expanded={open} />
          </div>
        </div>
        <nav className={`pub-mobile ${open ? "open" : ""}`} aria-label="Mobile">
          <NavLink to="/">Home</NavLink>
          {LINKS.map((l) => (
            <NavLink key={l.to} to={l.to}>
              {l.label}
            </NavLink>
          ))}
          {!me && <NavLink to="/login">Log in</NavLink>}
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
      <Footer />
    </>
  );
}

function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer-grid">
          <div className="stack gap-3">
            <Logo />
            <p className="small muted" style={{ maxWidth: 300 }}>
              Configurable AI agents that understand customer requests, answer from your own knowledge and execute
              authorized actions.
            </p>
          </div>
          <div>
            <h4>Product</h4>
            <ul>
              <li><Link to="/solutions">Solutions</Link></li>
              <li><Link to="/how-it-works">How it works</Link></li>
              <li><Link to="/industries">Industries</Link></li>
            </ul>
          </div>
          <div>
            <h4>Company</h4>
            <ul>
              <li><Link to="/about">About</Link></li>
              <li><Link to="/contact">Contact</Link></li>
            </ul>
          </div>
          <div>
            <h4>Account</h4>
            <ul>
              <li><Link to="/login">Log in</Link></li>
              <li><Link to="/register">Create an account</Link></li>
              <li><Link to="/contact">Request a demo</Link></li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© {BRAND.year} {BRAND.name}. Prototype platform: data shown in the app comes from your own workspace.</span>
          <span>Built on the AgentKit engine</span>
        </div>
      </div>
    </footer>
  );
}
