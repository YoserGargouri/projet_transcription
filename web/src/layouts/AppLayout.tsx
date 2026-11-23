import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity, BarChart3, BookOpen, Bot, ChevronsUpDown, LayoutDashboard, LogOut, Menu, MessageSquareText,
  Monitor, Moon, Plus, Settings, Sun, Workflow, Zap,
} from "lucide-react";
import { Button, Logo } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { AgentsProvider, useAgents } from "@/lib/agents";
import { initials } from "@/lib/format";
import { useTheme } from "@/lib/ui-state";

const NAV = [
  { to: "/app", label: "Overview", icon: <LayoutDashboard />, end: true },
  { to: "/app/agent", label: "AI Agent", icon: <Bot /> },
  { to: "/app/playground", label: "Playground", icon: <Zap /> },
  { to: "/app/conversations", label: "Conversations", icon: <MessageSquareText /> },
  { to: "/app/actions", label: "Actions", icon: <Workflow /> },
  { to: "/app/analytics", label: "Analytics", icon: <BarChart3 /> },
  { to: "/app/knowledge", label: "Knowledge Base", icon: <BookOpen /> },
  { to: "/app/settings", label: "Settings", icon: <Settings /> },
];

export function AppLayout() {
  return (
    <AgentsProvider>
      <Shell />
    </AgentsProvider>
  );
}

function Shell() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  const { me } = useAuth();

  return (
    <div className="shell">
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Application">
        <Link to="/" className="sidebar-brand">
          <Logo />
        </Link>
        <AgentSwitcher />
        <div className="sidebar-section">Workspace</div>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            {n.icon}
            {n.label}
          </NavLink>
        ))}
        <div className="sidebar-foot">
          <div className="usage-mini">
            <div className="row-between">
              <span className="muted">Workspace</span>
            </div>
            <div className="strong truncate" style={{ marginTop: 2 }}>{me?.workspace.name}</div>
          </div>
        </div>
      </aside>
      {open && <div className="overlay" style={{ zIndex: 54 }} onClick={() => setOpen(false)} />}
      <div className="main">
        <header className="topbar">
          <Button variant="ghost" size="sm" className="menu-btn" icon={<Menu />} onClick={() => setOpen(true)} aria-label="Open navigation" />
          <Crumb />
          <div style={{ marginLeft: "auto" }} className="row">
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

function Crumb() {
  const loc = useLocation();
  const item = [...NAV].reverse().find((n) => (n.end ? loc.pathname === n.to : loc.pathname.startsWith(n.to)));
  return (
    <div className="row small muted">
      <Activity size={14} />
      <span>{item?.label || ""}</span>
    </div>
  );
}

function AgentSwitcher() {
  const { agents, current, select, loading } = useAgents();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const nav = useNavigate();
  useOutside(ref, () => setOpen(false));
  if (loading) return <div className="skeleton" style={{ height: 44, margin: "4px 0" }} />;
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        className="btn btn-secondary btn-block"
        style={{ height: 44, justifyContent: "flex-start", padding: "0 10px" }}
        onClick={() => (agents.length ? setOpen((v) => !v) : nav("/app/agent?new=1"))}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="avatar" style={{ borderRadius: 6 }}>
          <Bot size={14} />
        </span>
        <span className="stack grow" style={{ textAlign: "left", lineHeight: 1.25 }}>
          <span className="xsmall subtle">Agent</span>
          <span className="truncate small strong">{current ? current.name : "Create your first agent"}</span>
        </span>
        {agents.length ? <ChevronsUpDown size={14} /> : <Plus size={14} />}
      </button>
      {open && (
        <div className="menu" role="menu" style={{ left: 0, right: "auto", width: "100%" }}>
          {agents.map((a) => (
            <button key={a.id} className="menu-item" role="menuitem" onClick={() => { select(a.id); setOpen(false); }}>
              <Bot />
              <span className="grow truncate">{a.name}</span>
              {current?.id === a.id && <span className="dot" style={{ color: "var(--accent)" }} />}
            </button>
          ))}
          <div className="menu-sep" />
          <button className="menu-item" role="menuitem" onClick={() => { setOpen(false); nav("/app/agent?new=1"); }}>
            <Plus />
            New agent
          </button>
        </div>
      )}
    </div>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const next = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
  const icon = theme === "light" ? <Sun /> : theme === "dark" ? <Moon /> : <Monitor />;
  return <Button variant="ghost" size="sm" icon={icon} onClick={() => setTheme(next)} aria-label={`Theme: ${theme}. Switch to ${next}`} title={`Theme: ${theme}`} />;
}

function UserMenu() {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const nav = useNavigate();
  useOutside(ref, () => setOpen(false));
  if (!me) return null;
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="btn btn-ghost btn-sm" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} style={{ padding: "0 4px" }}>
        <span className="avatar">{initials(me.user.name)}</span>
      </button>
      {open && (
        <div className="menu" role="menu">
          <div style={{ padding: "8px 8px 6px" }}>
            <div className="strong small">{me.user.name}</div>
            <div className="xsmall subtle truncate">{me.user.email}</div>
          </div>
          <div className="menu-sep" />
          <button className="menu-item" role="menuitem" onClick={() => { setOpen(false); nav("/app/settings"); }}>
            <Settings />
            Settings
          </button>
          <button className="menu-item" role="menuitem" onClick={async () => { await logout(); nav("/"); }}>
            <LogOut />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

function useOutside(ref: React.RefObject<HTMLElement>, cb: () => void) {
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) cb();
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [ref, cb]);
}
