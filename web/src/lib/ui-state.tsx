import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";

// ---------------------------------------------------------------- theme
export type Theme = "system" | "light" | "dark";

export function useTheme(): [Theme, (t: Theme) => void] {
  const read = (): Theme => {
    try {
      const t = localStorage.getItem("theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  };
  const [theme, setTheme] = useState<Theme>(read);
  const apply = useCallback((t: Theme) => {
    setTheme(t);
    try {
      if (t === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", t);
    } catch {
      /* storage unavailable: theme still applies for this page */
    }
    if (t === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
  }, []);
  return [theme, apply];
}

// ---------------------------------------------------------------- toasts
interface Toast { id: number; text: string; tone: "good" | "critical" }
const ToastCtx = createContext<(text: string, tone?: "good" | "critical") => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "good" | "critical" = "good") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 3800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div className="toast" key={t.id}>
            {t.tone === "good" ? <CheckCircle2 color="var(--good)" /> : <AlertCircle color="var(--critical)" />}
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

export function useEscape(onEscape: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onEscape();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onEscape, active]);
}
