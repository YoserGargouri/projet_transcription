import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/api/client";
import type { Agent } from "@/api/types";

interface AgentsCtx {
  agents: Agent[];
  loading: boolean;
  current: Agent | null;
  select: (id: string) => void;
  reload: () => Promise<void>;
}
const Ctx = createContext<AgentsCtx | null>(null);
const KEY = "currentAgent";

export function AgentsProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(() => {
    try {
      return localStorage.getItem(KEY);
    } catch {
      return null;
    }
  });

  const reload = useCallback(async () => {
    try {
      setAgents(await api.get<Agent[]>("/agents"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    reload();
  }, [reload]);

  const select = (id: string) => {
    setSelected(id);
    try {
      localStorage.setItem(KEY, id);
    } catch {
      /* per-viewer convenience only */
    }
  };
  const current = agents.find((a) => a.id === selected) || agents[0] || null;
  return <Ctx.Provider value={{ agents, loading, current, select, reload }}>{children}</Ctx.Provider>;
}

export function useAgents(): AgentsCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAgents outside AgentsProvider");
  return c;
}
