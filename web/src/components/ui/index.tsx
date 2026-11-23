import { useId, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, CircleDashed, Clock, Info, Inbox, UserRound, X, XCircle } from "lucide-react";
import type { ActionStatus, Outcome } from "@/api/types";
import { OUTCOMES, STATUSES } from "@/lib/format";
import { useEscape } from "@/lib/ui-state";
import { BRAND } from "@/brand";

// ---------------------------------------------------------------- button
type BtnVariant = "primary" | "secondary" | "ghost" | "accent" | "danger";
interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: BtnVariant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
  block?: boolean;
}
export function Button({ variant = "secondary", size = "md", loading, icon, block, className = "", children, disabled, ...rest }: BtnProps) {
  const cls = ["btn", `btn-${variant}`, size !== "md" && `btn-${size}`, !children && "btn-icon", block && "btn-block", className]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={cls} disabled={disabled || loading} {...rest}>
      {loading ? <span className="spinner" aria-hidden /> : icon}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- card
export function Card({ children, className = "", pad }: { children: ReactNode; className?: string; pad?: boolean }) {
  return <div className={`card ${pad ? "card-pad" : ""} ${className}`}>{children}</div>;
}
export function CardHeader({ title, sub, action }: { title: ReactNode; sub?: ReactNode; action?: ReactNode }) {
  return (
    <div className="card-header">
      <div className="grow">
        <h3>{title}</h3>
        {sub && <p>{sub}</p>}
      </div>
      {action}
    </div>
  );
}

// ---------------------------------------------------------------- badges
export function Badge({ tone = "neutral", children, icon }: { tone?: string; children: ReactNode; icon?: ReactNode }) {
  return (
    <span className={`badge ${tone !== "neutral" ? `badge-${tone}` : ""}`}>
      {icon}
      {children}
    </span>
  );
}

const STATUS_ICON: Record<ActionStatus, ReactNode> = {
  succeeded: <CheckCircle2 />,
  pending: <Clock />,
  failed: <XCircle />,
  requires_human: <UserRound />,
};
export function StatusBadge({ status }: { status: ActionStatus }) {
  const s = STATUSES[status] || { label: status, tone: "neutral" };
  return <Badge tone={s.tone} icon={STATUS_ICON[status]}>{s.label}</Badge>;
}
const OUTCOME_ICON: Record<Outcome, ReactNode> = {
  action_completed: <CheckCircle2 />,
  information_provided: <Info />,
  escalated: <UserRound />,
  in_progress: <CircleDashed />,
  unresolved: <AlertTriangle />,
};
export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  const o = OUTCOMES[outcome] || { label: outcome, tone: "neutral" };
  return <Badge tone={o.tone} icon={OUTCOME_ICON[outcome]}>{o.label}</Badge>;
}

// ---------------------------------------------------------------- form bits
export function Field({ label, hint, error, children, htmlFor }: { label: ReactNode; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {error ? <span className="field-error">{error}</span> : hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}
export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className="switch">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch-track" aria-hidden />
      {label && <span>{label}</span>}
    </label>
  );
}
export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: ReactNode; icon?: ReactNode }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}
export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: { value: T; label: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.value} role="tab" className="tab" aria-selected={value === t.value} onClick={() => onChange(t.value)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- states
export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon || <Inbox />}</div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="empty">
      <div className="empty-icon" style={{ color: "var(--critical-text)" }}>
        <AlertTriangle />
      </div>
      <h3>Couldn't load this</h3>
      <p>{error.message}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
export function Skeleton({ h = 16, w = "100%", style }: { h?: number; w?: number | string; style?: CSSProperties }) {
  return <div className="skeleton" style={{ height: h, width: w, ...style }} />;
}
export function Alert({ tone = "info", children, icon }: { tone?: "info" | "warning" | "critical" | "good"; children: ReactNode; icon?: ReactNode }) {
  const ic = icon ?? (tone === "good" ? <CheckCircle2 /> : tone === "info" ? <Info /> : <AlertTriangle />);
  return (
    <div className={`alert alert-${tone}`} role={tone === "critical" ? "alert" : undefined}>
      {ic}
      <div>{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------- stat tiles
export function Stat({ label, value, sub, icon }: { label: ReactNode; value: ReactNode; sub?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">
        {icon}
        {label}
      </div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {actions && <div className="row wrap">{actions}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- overlays
export function Drawer({ open, onClose, title, sub, children, footer }: { open: boolean; onClose: () => void; title: ReactNode; sub?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  useEscape(onClose, open);
  const id = useId();
  if (!open) return null;
  return createPortal(
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="drawer-header">
          <div className="grow">
            <h2 id={id} style={{ fontSize: "var(--fs-lg)" }}>
              {title}
            </h2>
            {sub && <div className="small muted" style={{ marginTop: 4 }}>{sub}</div>}
          </div>
          <Button variant="ghost" size="sm" icon={<X />} onClick={onClose} aria-label="Close" />
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-footer">{footer}</div>}
      </aside>
    </>,
    document.body,
  );
}

export function Modal({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode }) {
  useEscape(onClose, open);
  const id = useId();
  if (!open) return null;
  return createPortal(
    <>
      <div className="overlay" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="drawer-header">
          <h2 id={id} style={{ fontSize: "var(--fs-lg)" }}>
            {title}
          </h2>
          <Button variant="ghost" size="sm" icon={<X />} onClick={onClose} aria-label="Close" />
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-footer">{footer}</div>}
      </div>
    </>,
    document.body,
  );
}

export function ConfirmDialog({ open, title, body, confirmLabel = "Delete", onConfirm, onClose, loading }: { open: boolean; title: string; body: ReactNode; confirmLabel?: string; onConfirm: () => void; onClose: () => void; loading?: boolean }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="muted">{body}</p>
    </Modal>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total ? (page - 1) * pageSize + 1 : 0;
  return (
    <div className="pagination">
      <span>
        {from}–{Math.min(total, page * pageSize)} of {total}
      </span>
      <div className="row">
        <Button size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <Button size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- brand
export function Logo({ compact }: { compact?: boolean }) {
  return (
    <span className="logo">
      <svg className="logo-mark" viewBox="0 0 24 24" aria-hidden>
        <rect width="24" height="24" rx="6" fill="var(--primary)" />
        <path d="M6 15.5c1.6-4.5 3.3-7 6-7s4.4 2.5 6 7" fill="none" stroke="var(--primary-text)" strokeWidth="2" strokeLinecap="round" />
        <circle cx="12" cy="8.5" r="2" fill="var(--accent)" />
      </svg>
      {!compact && <BrandName />}
    </span>
  );
}
function BrandName() {
  return <span>{BRAND.name}</span>;
}
