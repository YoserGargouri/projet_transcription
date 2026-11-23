import { useMemo, useRef, useState } from "react";
import { BookOpen, Download, FileText, Plus, RotateCcw, Search, Trash2, Upload } from "lucide-react";
import { api, qs } from "@/api/client";
import type { KnowledgeEntry } from "@/api/types";
import { Alert, Badge, Button, Card, CardHeader, ConfirmDialog, Drawer, EmptyState, ErrorState, Field, PageHeader, Skeleton, Stat } from "@/components/ui";
import { NoAgent } from "@/pages/app/AgentConfig";
import { useAgents } from "@/lib/agents";
import { dateTime, relative } from "@/lib/format";
import { useAsync, useDebounced, useDocumentTitle } from "@/lib/hooks";
import { useToast } from "@/lib/ui-state";

type Draft = { id?: number; question: string; answer: string; variants: string; category: string };
const EMPTY: Draft = { question: "", answer: "", variants: "", category: "" };

export function Knowledge() {
  useDocumentTitle("Knowledge Base");
  const { current, loading, reload: reloadAgents } = useAgents();
  const toast = useToast();
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState<"delete" | "reset" | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const agentId = current?.id;
  const list = useAsync((s) => (agentId ? api.get<KnowledgeEntry[]>(`/agents/${agentId}/knowledge${qs({ q: dq })}`, s) : Promise.resolve([])), [agentId, dq]);
  const all = useAsync((s) => (agentId ? api.get<KnowledgeEntry[]>(`/agents/${agentId}/knowledge`, s) : Promise.resolve([])), [agentId]);

  const stats = useMemo(() => {
    const rows = all.data || [];
    const last = rows.reduce<string | null>((m, r) => (!m || r.updated_at > m ? r.updated_at : m), null);
    return {
      total: rows.length,
      template: rows.filter((r) => r.source === "template").length,
      manual: rows.filter((r) => r.source === "manual").length,
      imported: rows.filter((r) => r.source === "import").length,
      categories: new Set(rows.map((r) => r.category).filter(Boolean)).size,
      last,
    };
  }, [all.data]);

  if (!loading && !current) return <NoAgent />;
  if (!current) return null;

  const refresh = () => {
    list.reload();
    all.reload();
    reloadAgents();
  };
  const save = async () => {
    if (!draft) return;
    setSaving(true);
    const body = { question: draft.question, answer: draft.answer, category: draft.category, variants: draft.variants.split("\n").map((v) => v.trim()).filter(Boolean).join("|") };
    try {
      if (draft.id) await api.patch(`/agents/${current.id}/knowledge/${draft.id}`, body);
      else await api.post(`/agents/${current.id}/knowledge`, body);
      toast(draft.id ? "Entry updated" : "Entry added");
      setDraft(null);
      refresh();
    } catch (e) {
      toast((e as Error).message, "critical");
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    if (!draft?.id) return;
    setBusy(true);
    try {
      await api.del(`/agents/${current.id}/knowledge/${draft.id}`);
      toast("Entry deleted");
      setConfirm(null);
      setDraft(null);
      refresh();
    } catch (e) {
      toast((e as Error).message, "critical");
    } finally {
      setBusy(false);
    }
  };
  const reset = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ entries: number }>(`/agents/${current.id}/knowledge/reset`);
      toast(`Knowledge base restored (${r.entries} template entries)`);
      setConfirm(null);
      refresh();
    } catch (e) {
      toast((e as Error).message, "critical");
    } finally {
      setBusy(false);
    }
  };
  const importCsv = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    try {
      const r = await api.post<{ added: number; skipped: number }>(`/agents/${current.id}/knowledge/import`, fd);
      toast(`${r.added} entries imported${r.skipped ? `, ${r.skipped} skipped` : ""}`);
      refresh();
    } catch (e) {
      toast((e as Error).message, "critical");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  const exportCsv = () => {
    const rows = all.data || [];
    const esc = (s: string) => `"${s.replace(/"/g, '""')}"`;
    const csv = ["id,category,question,answer,variants", ...rows.map((r) => [r.entry_id, r.category, r.question, r.answer, r.variants].map(esc).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `knowledge-${current.name.replace(/\W+/g, "-").toLowerCase()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const open = (e: KnowledgeEntry) => setDraft({ id: e.id, question: e.question, answer: e.answer, category: e.category, variants: e.variants.split("|").filter(Boolean).join("\n") });

  return (
    <>
      <PageHeader
        title="Knowledge Base"
        sub={<>Information <b>{current.name}</b> may use to answer. The model writes answers from these entries and must cite them; it cannot state facts that are not here.</>}
        actions={
          <>
            <input ref={fileRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} />
            <Button size="sm" icon={<Upload />} onClick={() => fileRef.current?.click()} loading={busy && !confirm}>Import CSV</Button>
            <Button size="sm" icon={<Download />} onClick={exportCsv} disabled={!all.data?.length}>Export</Button>
            <Button size="sm" variant="primary" icon={<Plus />} onClick={() => setDraft({ ...EMPTY })}>Add entry</Button>
          </>
        }
      />

      <div className="stat-row" style={{ marginBottom: 16 }}>
        <Stat label="Entries" value={stats.total} sub={`${stats.categories} categories`} />
        <Stat label="From template" value={stats.template} sub="copied when the agent was created" />
        <Stat label="Added by you" value={stats.manual + stats.imported} sub={`${stats.manual} manual · ${stats.imported} imported`} />
        <Stat label="Last updated" value={<span style={{ fontSize: "var(--fs-xl)" }}>{relative(stats.last)}</span>} sub="Status: ready · used from the next conversation" />
      </div>

      <div className="split-21">
        <Card>
          <div className="card-header">
            <div className="input-icon grow" style={{ maxWidth: 360 }}>
              <Search />
              <input className="input input-sm" placeholder="Search questions, answers, categories" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search knowledge" />
            </div>
            <span className="small subtle">{list.data?.length ?? 0} shown</span>
          </div>
          {list.error ? (
            <ErrorState error={list.error} onRetry={list.reload} />
          ) : list.loading && !list.data ? (
            <div className="card-body stack gap-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={36} />)}</div>
          ) : list.data?.length === 0 ? (
            <EmptyState icon={<BookOpen />} title={q ? "No entry matches" : "No entries"} action={<Button size="sm" icon={<Plus />} onClick={() => setDraft({ ...EMPTY })}>Add entry</Button>} />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Question & answer</th>
                    <th>Category</th>
                    <th>Source</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data?.map((e) => (
                    <tr key={e.id} className="clickable" onClick={() => open(e)}>
                      <td className="id">{e.entry_id}</td>
                      <td style={{ maxWidth: 460 }}>
                        <div className="small strong">{e.question}</div>
                        <div className="small muted truncate">{e.answer}</div>
                      </td>
                      <td>{e.category ? <Badge>{e.category}</Badge> : <span className="subtle">—</span>}</td>
                      <td><Badge tone={e.source === "template" ? "outline" : "accent"}>{e.source}</Badge></td>
                      <td className="small subtle">{dateTime(e.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="stack gap-4">
          <Card>
            <CardHeader title="Knowledge sources" />
            <div className="card-body stack gap-3">
              <Source icon={<BookOpen />} title="Questions & answers" status={<Badge tone="good">Active</Badge>}>
                {stats.total} entries. Used by the model as its only source for practical answers.
              </Source>
              <Source icon={<Upload />} title="CSV import" status={<Badge tone="good">Supported</Badge>}>
                Columns <code>question</code>, <code>answer</code>; optional <code>category</code>, <code>variants</code> (separated by |).
              </Source>
              <Source icon={<FileText />} title="Documents (PDF, Word, web pages)" status={<Badge>Roadmap</Badge>}>
                Extracting entries from documents is planned; today, add their key facts as entries.
              </Source>
            </div>
          </Card>
          <Card>
            <CardHeader title="Restore template" sub="Replace all entries with the template's original knowledge base." />
            <div className="card-body">
              <Button size="sm" variant="danger" icon={<RotateCcw />} onClick={() => setConfirm("reset")}>Restore template entries</Button>
            </div>
          </Card>
        </div>
      </div>

      <Drawer
        open={!!draft}
        onClose={() => setDraft(null)}
        title={draft?.id ? "Edit entry" : "New entry"}
        sub="Write facts as you would say them on the phone. The agent may rephrase but never add facts."
        footer={
          <>
            {draft?.id && <Button variant="danger" icon={<Trash2 />} onClick={() => setConfirm("delete")} style={{ marginRight: "auto" }}>Delete</Button>}
            <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
            <Button variant="primary" onClick={save} loading={saving} disabled={!draft || draft.question.trim().length < 3 || !draft.answer.trim()}>Save</Button>
          </>
        }
      >
        {draft && (
          <div className="form-grid">
            <Field label="Question" htmlFor="k-q">
              <input id="k-q" className="input" maxLength={500} value={draft.question} onChange={(e) => setDraft({ ...draft, question: e.target.value })} autoFocus />
            </Field>
            <Field label="Answer" htmlFor="k-a" hint="The facts the agent may state.">
              <textarea id="k-a" className="textarea" rows={5} maxLength={3000} value={draft.answer} onChange={(e) => setDraft({ ...draft, answer: e.target.value })} />
            </Field>
            <Field label="Other ways customers ask" htmlFor="k-v" hint="One per line. Helps the search used by the rules fallback.">
              <textarea id="k-v" className="textarea" rows={4} value={draft.variants} onChange={(e) => setDraft({ ...draft, variants: e.target.value })} />
            </Field>
            <Field label="Category" htmlFor="k-c">
              <input id="k-c" className="input" maxLength={60} value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })} />
            </Field>
            <Alert tone="info">Changes apply to conversations started after saving.</Alert>
          </div>
        )}
      </Drawer>
      <ConfirmDialog open={confirm === "delete"} title="Delete this entry?" body="The agent will no longer be able to use this information." onClose={() => setConfirm(null)} onConfirm={remove} loading={busy} />
      <ConfirmDialog open={confirm === "reset"} title="Restore the template entries?" body="All current entries, including the ones you added or edited, are replaced by the template's knowledge base." confirmLabel="Restore" onClose={() => setConfirm(null)} onConfirm={reset} loading={busy} />
    </>
  );
}

function Source({ icon, title, status, children }: { icon: React.ReactNode; title: string; status: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="cap">
      <div className="cap-icon">{icon}</div>
      <div className="stack gap-1 grow">
        <div className="row-between"><span className="small strong">{title}</span>{status}</div>
        <span className="xsmall subtle">{children}</span>
      </div>
    </div>
  );
}
