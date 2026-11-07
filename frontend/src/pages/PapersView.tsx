import { useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ChevronUp, ExternalLink, FileUp, Search } from "lucide-react";
import { api } from "../api";
import type { Paper } from "../types";
import { Empty, Spinner, useToast } from "../components/ui";
import { useSession } from "./SessionLayout";

const SOURCE_LABEL: Record<string, string> = { openalex: "OpenAlex", semantic_scholar: "Semantic Scholar", pubmed: "PubMed", arxiv: "arXiv", upload: "Uploaded" };

function PaperCard({ p }: { p: Paper }) {
  const [open, setOpen] = useState(false);
  const authors = p.authors.length > 4 ? `${p.authors.slice(0, 4).join(", ")} et al.` : p.authors.join(", ");
  return (
    <article className="card flex gap-4 p-5">
      <div className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-teal-soft text-sm font-bold text-teal-ink" aria-label={`Paper ${p.n}`}>{p.n}</div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h3 className="h-serif text-[17px] leading-snug">
          {p.url ? <a href={p.url} target="_blank" rel="noreferrer" className="text-ink hover:text-teal">{p.title}<ExternalLink size={13} className="ml-1 inline align-baseline text-ink-muted" aria-hidden="true" /></a> : p.title}
        </h3>
        <div className="text-[13px] text-ink-muted">{[authors, p.year, p.journal].filter(Boolean).join(" · ")}</div>
        <div className="flex flex-wrap items-center gap-1.5">
          {p.citations > 0 && <span className="chip">{p.citations.toLocaleString()} citations</span>}
          {p.uploaded && <span className="chip chip-amber">Your upload</span>}
          {p.found_in.filter((s) => s !== "upload").map((s) => <span key={s} className="chip chip-teal">{SOURCE_LABEL[s] ?? s}</span>)}
          {p.doi && <span className="text-xs text-ink-muted">doi:{p.doi}</span>}
        </div>
        {p.abstract && (
          <div>
            <p className={`text-sm text-ink-2 ${open ? "" : "line-clamp-2"}`}>{p.abstract}</p>
            <button className="mt-1 flex items-center gap-1 text-[13px] font-semibold text-teal" onClick={() => setOpen(!open)} aria-expanded={open}>
              {open ? <>Show less <ChevronUp size={14} /></> : <>Read abstract <ChevronDown size={14} /></>}
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

export default function PapersView() {
  const { sid, session, papers, running, runAnalysis } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"relevance" | "year" | "citations">("relevance");

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    let list = t ? papers.filter((p) => `${p.title} ${p.authors.join(" ")} ${p.abstract ?? ""}`.toLowerCase().includes(t)) : papers;
    if (sort === "year") list = [...list].sort((a, b) => (b.year ?? 0) - (a.year ?? 0));
    if (sort === "citations") list = [...list].sort((a, b) => b.citations - a.citations);
    return list;
  }, [papers, q, sort]);

  async function upload(f: File) {
    setUploading(true);
    try {
      const r = await api.upload(sid, f);
      toast(`Added "${r.title}"`);
      qc.invalidateQueries({ queryKey: ["papers", sid] });
      qc.invalidateQueries({ queryKey: ["session", sid] });
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  const d = session.discovery;
  const years = papers.map((p) => p.year).filter((y): y is number => !!y);
  const stats = [
    { label: "Papers", value: papers.length },
    { label: "Years covered", value: years.length ? `${Math.min(...years)}–${Math.max(...years)}` : "—" },
    { label: "Sources searched", value: d ? Object.values(d.sources).filter((s) => s.found > 0).length : "—" },
    { label: "Candidates screened", value: d?.candidates ?? "—" },
  ];

  if (!papers.length) {
    return (
      <Empty icon={<BookOpen size={22} />} title={running ? "Finding papers…" : "No papers yet"}>
        {running ? "Results will appear here as soon as the search finishes." : (
          <div className="flex flex-col items-center gap-3">
            <span>Search the free paper databases for your topic, or upload a PDF you already have.</span>
            {session.can_edit && <div className="flex gap-2">
              <button className="btn btn-primary" onClick={runAnalysis}>Find papers</button>
              <button className="btn" onClick={() => fileRef.current?.click()} disabled={uploading}>{uploading ? <Spinner /> : <FileUp size={16} />}Upload PDF</button>
            </div>}
            <input ref={fileRef} type="file" accept="application/pdf" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </div>
        )}
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="card p-4"><div className="text-2xl font-bold">{s.value}</div><div className="text-[13px] text-ink-muted">{s.label}</div></div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-[220px] flex-1">
          <span className="sr-only">Filter papers</span>
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
          <input className="input pl-9" placeholder="Filter by title, author or abstract" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm text-ink-muted">Sort
          <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="relevance">Relevance</option><option value="year">Newest</option><option value="citations">Most cited</option>
          </select>
        </label>
        {session.can_edit && <>
          <button className="btn" onClick={() => fileRef.current?.click()} disabled={uploading}>{uploading ? <Spinner /> : <FileUp size={16} aria-hidden="true" />}Upload PDF</button>
          <input ref={fileRef} type="file" accept="application/pdf" className="sr-only" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </>}
      </div>
      {q && <div className="text-[13px] text-ink-muted">{shown.length} of {papers.length} papers match</div>}
      <div className="flex flex-col gap-3">{shown.map((p) => <PaperCard key={p.id} p={p} />)}</div>
    </div>
  );
}
