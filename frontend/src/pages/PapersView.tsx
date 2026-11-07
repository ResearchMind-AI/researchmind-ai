import { useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ChevronUp, ExternalLink, FileText, Pencil, Search, Star, Upload, X } from "lucide-react";
import { api } from "../api";
import { REMOVE_REASONS, type Paper } from "../types";
import { Empty, Modal, Spinner, useToast } from "../components/ui";
import { useSession } from "./SessionLayout";

const SOURCE_LABEL: Record<string, string> = {
  openalex: "OpenAlex", semantic_scholar: "Semantic Scholar", pubmed: "PubMed", arxiv: "arXiv", upload: "Uploaded", doi: "Added by DOI",
};
const reasonLabel = (r: string | null) => REMOVE_REASONS.find((x) => x.value === r)?.label;
type View = "kept" | "key" | "removed";


function NoteEditor({ p, onSave, onClose }: { p: Paper; onSave: (v: string) => void; onClose: () => void }) {
  const [v, setV] = useState(p.notes ?? "");
  return (
    <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); onSave(v); }}>
      <label className="sr-only" htmlFor={`note-${p.id}`}>Note on paper {p.n}</label>
      <textarea id={`note-${p.id}`} className="textarea min-h-[64px] text-sm" value={v} autoFocus maxLength={4000}
        onChange={(e) => setV(e.target.value)} placeholder="Why it matters, where to use it, doubts…"
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSave(v); }} />
      <div className="flex gap-2"><button className="btn btn-sm btn-primary">Save note</button><button type="button" className="btn btn-sm" onClick={onClose}>Cancel</button></div>
    </form>
  );
}

function PaperCard({ p, canEdit, onUpdate, onUpload }: {
  p: Paper; canEdit: boolean;
  onUpdate: (p: Paper, patch: Partial<Paper>) => void;
  onUpload: (p: Paper) => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const authors = p.authors.length > 4 ? `${p.authors.slice(0, 4).join(", ")} et al.` : p.authors.join(", ");
  const removed = p.status === "removed";
  return (
    <article className={`flex flex-wrap gap-4 border-b border-line px-5 py-[18px] last:border-b-0 md:flex-nowrap ${p.is_key ? "bg-[#FFFCF7]" : ""} ${removed ? "bg-ground/60" : ""}`}>
      <div className={`flex h-[34px] w-[34px] flex-none items-center justify-center rounded-[9px] text-[13px] font-bold ${removed ? "bg-chip text-ink-muted" : "bg-teal-soft text-teal-ink"}`} aria-label={`Paper ${p.n}`}>{p.n}</div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h3 className={`h-serif text-[17px] leading-snug ${removed ? "text-ink-muted" : ""}`}>
          {p.url ? <a href={p.url} target="_blank" rel="noreferrer" className="text-inherit hover:text-teal">{p.title}<ExternalLink size={13} className="ml-1 inline align-baseline text-ink-muted" aria-hidden="true" /></a> : p.title}
        </h3>
        <div className="text-[13px] text-ink-muted">{[authors, p.year, p.journal].filter(Boolean).join(" · ")}</div>
        <div className="flex flex-wrap items-center gap-1.5">
          {removed && <span className="chip">Removed{p.removed_reason ? ` · ${reasonLabel(p.removed_reason)}` : ""}</span>}
          {p.full_text
            ? <span className="chip chip-teal"><FileText size={12} aria-hidden="true" />Full text{p.full_text_source === "upload" ? " · your PDF" : ""}</span>
            : <span className="chip">Abstract only</span>}
          {!p.full_text && canEdit && !removed && <button className="text-[13px] font-semibold text-teal hover:underline" onClick={() => onUpload(p)}>Have the PDF? Upload it</button>}
          {p.citations > 0 && <span className="chip">Cited {p.citations.toLocaleString()}×</span>}
          {p.found_in.filter((s) => s !== "upload").map((s) => <span key={s} className="chip">{SOURCE_LABEL[s] ?? s}</span>)}
          {p.uploaded && <span className="chip chip-amber">Your upload</span>}
        </div>
        {editing ? <NoteEditor p={p} onClose={() => setEditing(false)} onSave={(v) => { onUpdate(p, { notes: v }); setEditing(false); }} />
          : p.notes ? (
            <div className="flex items-baseline gap-1.5 text-[13px] text-ink-2">
              <span className="font-semibold">Your note:</span><span className="whitespace-pre-wrap">{p.notes}</span>
              {canEdit && <button className="ml-1 text-ink-muted hover:text-ink" onClick={() => setEditing(true)} aria-label="Edit note"><Pencil size={12} /></button>}
            </div>
          ) : canEdit && !removed && <button className="self-start text-[13px] font-semibold text-ink-muted hover:text-ink" onClick={() => setEditing(true)}>+ Add a note</button>}
        {p.abstract && (
          <div>
            <p className={`text-sm text-ink-2 ${open ? "" : "line-clamp-2"}`}>{p.abstract}</p>
            <button className="mt-1 flex items-center gap-1 text-[13px] font-semibold text-teal" onClick={() => setOpen(!open)} aria-expanded={open}>
              {open ? <>Show less <ChevronUp size={14} /></> : <>Read abstract <ChevronDown size={14} /></>}
            </button>
          </div>
        )}
      </div>
      {canEdit && (
        <div className="flex flex-none gap-1.5 self-start">
          {removed
            ? <button className="btn btn-sm" onClick={() => onUpdate(p, { status: "kept" })}>Restore</button>
            : <>
                <button className={`btn btn-sm ${p.is_key ? "border-[#F3D3A6] bg-amber-soft text-amber-ink" : ""}`} aria-pressed={p.is_key}
                  onClick={() => onUpdate(p, { is_key: !p.is_key })}>
                  <Star size={15} fill={p.is_key ? "currentColor" : "none"} aria-hidden="true" />Key paper
                </button>
                <button className="btn btn-sm" onClick={() => onUpdate(p, { status: "removed" })}>Remove</button>
              </>}
        </div>
      )}
    </article>
  );
}

function DoiModal({ onClose, onAdd }: { onClose: () => void; onAdd: (doi: string) => Promise<void> }) {
  const [doi, setDoi] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await onAdd(doi); onClose(); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  }
  return (
    <Modal title="Add a paper by DOI" onClose={onClose}>
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <div><label className="label" htmlFor="doi">DOI or doi.org link</label>
          <input id="doi" className="input" required value={doi} onChange={(e) => setDoi(e.target.value)} placeholder="10.1038/s41591-023-02448-8" autoFocus /></div>
        {err && <div className="rounded-[10px] bg-[#FBEFEE] px-3 py-2 text-sm text-[#7F1D1D]" role="alert">{err}</div>}
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || doi.trim().length < 6}>{busy && <Spinner />}Add paper</button></div>
      </form>
    </Modal>
  );
}

export default function PapersView() {
  const { sid, session, papers, kept, running, runAnalysis } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const attachTo = useRef<Paper | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [view, setView] = useState<View>(() => (["kept", "key", "removed"].includes(params.get("view") ?? "") ? params.get("view") as View : "kept"));
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"number" | "year" | "citations">("number");
  const [doiOpen, setDoiOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [justRemoved, setJustRemoved] = useState<Paper | null>(null);
  const canEdit = session.can_edit;

  useEffect(() => {
    if (!justRemoved) return;
    const t = setTimeout(() => setJustRemoved(null), 9000);
    return () => clearTimeout(t);
  }, [justRemoved]);

  const removed = papers.filter((p) => p.status === "removed");
  const keyPapers = kept.filter((p) => p.is_key);
  const withText = kept.filter((p) => p.full_text).length;
  const list = view === "kept" ? kept : view === "key" ? keyPapers : removed;
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    let out = t ? list.filter((p) => `${p.title} ${p.authors.join(" ")} ${p.abstract ?? ""} ${p.notes ?? ""}`.toLowerCase().includes(t)) : list;
    if (sort === "year") out = [...out].sort((a, b) => (b.year ?? 0) - (a.year ?? 0));
    if (sort === "citations") out = [...out].sort((a, b) => b.citations - a.citations);
    return out;
  }, [list, q, sort]);

  function refreshAfterChange() {
    // Themes and the writing guide follow the kept papers, so they're re-checked next time they're opened.
    for (const k of ["session", "analysis", "writing"]) qc.invalidateQueries({ queryKey: [k, sid] });
    qc.invalidateQueries({ queryKey: ["sessions"] });
  }

  async function update(p: Paper, patch: Partial<Paper>) {
    const prev = qc.getQueryData<Paper[]>(["papers", sid]);
    qc.setQueryData<Paper[]>(["papers", sid], (xs) => xs?.map((x) => (x.id === p.id
      ? { ...x, ...patch, ...(patch.status === "removed" ? { is_key: false } : {}), ...(patch.status === "kept" ? { removed_reason: null } : {}) }
      : x)));
    try {
      const fresh = await api.updatePaper(sid, p.id, patch);
      qc.setQueryData<Paper[]>(["papers", sid], (xs) => xs?.map((x) => (x.id === p.id ? fresh : x)));
      if (patch.status === "removed") setJustRemoved(fresh);
      if (patch.status === "kept" && justRemoved?.id === p.id) setJustRemoved(null);
      if (patch.status === "kept" && !justRemoved) toast(`Paper ${p.n} restored`);
      if (patch.status || patch.is_key !== undefined) refreshAfterChange();
    } catch (e) {
      qc.setQueryData(["papers", sid], prev);
      toast((e as Error).message, "error");
    }
  }

  async function uploadFiles(files: File[], target?: Paper | null) {
    const pdfs = files.filter((f) => /\.(pdf|docx)$/i.test(f.name));
    if (!pdfs.length) { toast("Only PDF or Word (.docx) files can be added.", "error"); return; }
    let added = 0, attached = 0;
    for (const [i, f] of pdfs.entries()) {
      setUploading(pdfs.length > 1 ? `Reading ${i + 1} of ${pdfs.length}: ${f.name}` : `Reading ${f.name}`);
      try {
        const r = await api.upload(sid, f, target?.id);
        if (r.attached) attached++; else added++;
      } catch (e) { toast(`${f.name}: ${(e as Error).message}`, "error"); }
    }
    setUploading(null);
    if (fileRef.current) fileRef.current.value = "";
    attachTo.current = null;
    qc.invalidateQueries({ queryKey: ["papers", sid] });
    refreshAfterChange();
    const parts = [added && `${added} new paper${added > 1 ? "s" : ""} added`, attached && `full text attached to ${attached} paper${attached > 1 ? "s" : ""}`].filter(Boolean);
    if (parts.length) toast(parts.join(", "));
  }

  function pickFiles(target?: Paper) { attachTo.current = target ?? null; fileRef.current?.click(); }
  function onDrop(e: DragEvent) {
    e.preventDefault(); setDragging(false);
    if (canEdit) uploadFiles(Array.from(e.dataTransfer.files));
  }
  async function addDoi(doi: string) {
    const p = await api.addByDoi(sid, doi);
    qc.invalidateQueries({ queryKey: ["papers", sid] });
    refreshAfterChange();
    toast(`Added as paper ${p.n}`);
  }

  const fileInput = <input ref={fileRef} type="file" multiple accept=".pdf,.docx,application/pdf" className="sr-only" tabIndex={-1}
    onChange={(e) => e.target.files?.length && uploadFiles(Array.from(e.target.files), attachTo.current)} />;

  if (!papers.length) {
    return (
      <Empty icon={<BookOpen size={22} />} title={running ? "Finding papers…" : "No papers yet"}>
        {running ? "Results will appear here as soon as the search finishes." : (
          <div className="flex flex-col items-center gap-3">
            <span>Search the free paper databases for your topic, or add papers you already have.</span>
            {canEdit && <div className="flex flex-wrap justify-center gap-2">
              <button className="btn btn-primary" onClick={runAnalysis}>Find papers</button>
              <button className="btn" onClick={() => pickFiles()} disabled={!!uploading}>{uploading ? <Spinner /> : <Upload size={16} />}Upload PDFs</button>
              <button className="btn" onClick={() => setDoiOpen(true)}>Add by DOI</button>
            </div>}
            {uploading && <span className="text-[13px]">{uploading}</span>}
            {fileInput}
          </div>
        )}
        {doiOpen && <DoiModal onClose={() => setDoiOpen(false)} onAdd={addDoi} />}
      </Empty>
    );
  }

  const sc = session.screening;
  const segs: { v: View; label: string; n: number }[] = [
    { v: "kept", label: "Kept", n: kept.length }, { v: "key", label: "Key papers", n: keyPapers.length }, { v: "removed", label: "Removed", n: removed.length },
  ];

  return (
    <div className="flex flex-col gap-5" onDragOver={(e) => { if (canEdit) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }} onDrop={onDrop}>
      {fileInput}
      <p className="-mb-1 max-w-3xl text-sm text-ink-muted"><b className="text-ink">Papers</b>: remove the ones that aren't relevant and star the key ones. Themes, gaps, answers and the writing guide only use the papers you keep.</p>

      <section className="card flex flex-wrap items-center gap-x-4 gap-y-3 px-5 py-4" aria-label="Screening summary">
        {sc.screened != null && <><div><div className="text-2xl font-bold">{sc.screened}</div><div className="text-xs font-semibold text-ink-muted">Screened</div></div><span className="text-ink-muted" aria-hidden="true">→</span></>}
        <div><div className="text-2xl font-bold">{papers.length}</div><div className="text-xs font-semibold text-ink-muted">Found</div></div>
        <span className="text-ink-muted" aria-hidden="true">→</span>
        <div><div className="text-2xl font-bold text-teal">{kept.length}</div><div className="text-xs font-semibold text-ink-muted">Kept</div></div>
        <div className="ml-1"><div className="text-2xl font-bold text-ink-muted">{removed.length}</div><div className="text-xs font-semibold text-ink-muted">Removed</div></div>
        <div className="flex min-w-[220px] flex-1 flex-col gap-1.5 md:ml-auto md:max-w-[320px]">
          <div className="flex justify-between text-[13px]"><span className="font-semibold">Full text for {withText} of {kept.length}</span><span className="text-ink-muted">rest: abstract only</span></div>
          <div className="h-2 rounded-full bg-chip" aria-hidden="true"><div className="h-2 rounded-full bg-teal" style={{ width: `${kept.length ? (withText / kept.length) * 100 : 0}%` }} /></div>
        </div>
      </section>

      <section className="card" aria-label="Papers">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3.5">
          <div className="flex gap-1 rounded-[10px] bg-chip p-1" role="tablist" aria-label="Show papers">
            {segs.map((s) => (
              <button key={s.v} role="tab" aria-selected={view === s.v} onClick={() => setView(s.v)}
                className={`flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-[13px] font-semibold ${view === s.v ? "bg-white text-ink shadow-sm" : "text-ink-muted"}`}>
                {s.v === "key" && <Star size={13} aria-hidden="true" />}{s.label}<span className="rounded-full bg-chip px-1.5 text-xs">{s.n}</span>
              </button>
            ))}
          </div>
          <label className="relative min-w-[200px] flex-1">
            <span className="sr-only">Filter papers</span>
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
            <input className="input pl-9" placeholder="Filter by title, author, abstract or note" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-muted">Sort
            <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
              <option value="number">Number</option><option value="year">Newest</option><option value="citations">Most cited</option>
            </select>
          </label>
        </div>
        {q && <div className="border-b border-line px-5 py-2 text-[13px] text-ink-muted">{shown.length} of {list.length} match</div>}
        {shown.length === 0 && (
          <div className="px-5 py-10 text-center text-sm text-ink-muted">
            {view === "key" ? "No key papers yet. Use ☆ Key paper on the ones you'll lean on most." : view === "removed" ? "Nothing removed. Removed papers show here and can be restored any time." : "No papers match."}
          </div>
        )}
        {shown.map((p) => <PaperCard key={p.id} p={p} canEdit={canEdit} onUpdate={update} onUpload={(x) => pickFiles(x)} />)}
      </section>

      {canEdit && (
        <section aria-label="Add your own papers"
          className={`flex flex-wrap items-center gap-4 rounded-card border-2 border-dashed px-5 py-5 ${dragging ? "border-teal bg-teal-soft" : "border-teal-line bg-teal-wash"}`}>
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white text-teal-ink">{uploading ? <Spinner /> : <Upload size={20} aria-hidden="true" />}</div>
          <div className="min-w-[240px] flex-1">
            <div className="text-[15px] font-semibold">{uploading ?? (dragging ? "Drop to add" : "Add your own papers")}</div>
            <div className="text-[13px] text-ink-muted">Drop PDFs here (several at once) or add a paper by its DOI. A PDF of a paper that's already here becomes its full text.</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-sm" onClick={() => pickFiles()} disabled={!!uploading}>Choose PDFs</button>
            <button className="btn btn-sm" onClick={() => setDoiOpen(true)}>Add by DOI</button>
            <button className="btn btn-sm" onClick={runAnalysis} disabled={running}>{running && <Spinner />}Search for more</button>
          </div>
        </section>
      )}

      {justRemoved && (
        <div role="status" className="fixed bottom-5 left-1/2 z-40 flex w-[min(760px,calc(100vw-32px))] -translate-x-1/2 flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-navy px-4 py-3 text-white shadow-xl">
          <span className="font-semibold">Paper {justRemoved.n} removed.</span>
          {!justRemoved.removed_reason ? <>
            <span className="text-[13px] text-[#B8C5D2]">Why? (optional)</span>
            <span className="flex flex-wrap gap-1.5">
              {REMOVE_REASONS.slice(0, 4).map((r) => (
                <button key={r.value} className="btn btn-sm border-navy-line bg-navy-2 text-white hover:bg-navy-3"
                  onClick={async () => { await update(justRemoved, { removed_reason: r.value }); setJustRemoved(null); }}>{r.label}</button>
              ))}
            </span>
          </> : <span className="text-[13px] text-[#B8C5D2]">Reason: {reasonLabel(justRemoved.removed_reason)}</span>}
          <span className="ml-auto flex items-center gap-1">
            <button className="btn btn-sm border-transparent bg-transparent text-teal-bright hover:bg-navy-2" onClick={() => update(justRemoved, { status: "kept" })}>Undo</button>
            <button className="rounded p-1 text-white/70 hover:text-white" aria-label="Dismiss" onClick={() => setJustRemoved(null)}><X size={16} /></button>
          </span>
        </div>
      )}
      {doiOpen && <DoiModal onClose={() => setDoiOpen(false)} onAdd={addDoi} />}
    </div>
  );
}
