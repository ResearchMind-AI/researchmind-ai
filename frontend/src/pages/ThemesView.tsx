import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, RefreshCw } from "lucide-react";
import { api } from "../api";
import { CitedText, Empty, ErrorNote, PageLoading, RefBadges, Spinner, useToast } from "../components/ui";
import { useSession } from "./SessionLayout";

export default function ThemesView() {
  const { sid, session, papers, paperMap, running } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const analysis = useQuery({ queryKey: ["analysis", sid], queryFn: () => api.analysis(sid) });
  const regen = useMutation({
    mutationFn: () => api.regenerateThemes(sid),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["analysis", sid] }); qc.invalidateQueries({ queryKey: ["session", sid] }); toast("Themes updated"); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  if (analysis.isLoading) return <PageLoading />;
  if (analysis.error) return <ErrorNote error={analysis.error} />;
  const themes = analysis.data?.analysis?.themes ?? [];
  // key_paper_ids are DB ids; map them to the session's paper numbers.
  const nById = new Map(papers.map((p) => [p.id, p.n]));
  const refsFor = (ids: number[]) => ids.map((i) => nById.get(i)).filter((n): n is number => !!n);
  // Findings end with "(id=12, id=40)"; turn those into numbered citations.
  const cite = (text: string) => text.replace(/\s*\(((?:\s*id\s*=\s*\d+\s*,?)+)\)/g, (_m, inner: string) =>
    " " + refsFor([...inner.matchAll(/\d+/g)].map((m) => Number(m[0]))).map((n) => `[${n}]`).join(""));

  if (!themes.length) {
    return (
      <Empty icon={<Layers size={22} />} title={running ? "Finding themes…" : "No themes yet"}>
        {running ? "Themes appear once papers have been found." : (
          <div className="flex flex-col items-center gap-3">
            <span>{papers.length ? "Group your papers into themes with key findings." : "Find papers first, then themes are generated automatically."}</span>
            {session.can_edit && papers.length > 0 && <button className="btn btn-primary" onClick={() => regen.mutate()} disabled={regen.isPending}>{regen.isPending && <Spinner />}Generate themes</button>}
          </div>
        )}
      </Empty>
    );
  }

  const max = Math.max(...themes.map((t) => t.size), 1);
  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-3 rounded-card bg-navy p-6 text-navy-text">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-navy-muted">Overview · {themes.length} themes across {papers.length} papers</div>
          {session.can_edit && <button className="btn btn-sm border-navy-line bg-transparent text-white hover:bg-navy-2" onClick={() => regen.mutate()} disabled={regen.isPending || running}>
            {regen.isPending ? <Spinner /> : <RefreshCw size={14} aria-hidden="true" />}Regenerate
          </button>}
        </div>
        {analysis.data?.analysis?.overview && <p className="h-serif text-[19px] leading-relaxed text-white">{analysis.data.analysis.overview}</p>}
        <div className="flex flex-wrap gap-2">
          {themes.map((t, i) => <a key={i} href={`#theme-${i}`} className="rounded-full bg-white/[0.08] px-3 py-1 text-[13px] text-white no-underline hover:bg-white/15">{t.label} · {t.size}</a>)}
        </div>
      </section>
      <div className="grid gap-4 lg:grid-cols-2">
        {themes.map((t, i) => (
          <article key={i} id={`theme-${i}`} className="card flex scroll-mt-6 flex-col gap-3 p-5">
            <div className="flex items-start justify-between gap-3">
              <h3 className="h-serif text-[19px] leading-snug">{t.label}</h3>
              <span className="chip flex-none">{t.size} paper{t.size === 1 ? "" : "s"}</span>
            </div>
            <div className="h-1.5 rounded-full bg-chip" aria-hidden="true"><div className="h-1.5 rounded-full bg-teal" style={{ width: `${(t.size / max) * 100}%` }} /></div>
            <p className="text-sm text-ink-2"><CitedText text={cite(t.summary)} papers={paperMap} /></p>
            {t.key_findings.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <div className="sub">Key findings</div>
                <ul className="flex flex-col gap-1.5 text-sm">
                  {t.key_findings.map((f, j) => <li key={j} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-teal" aria-hidden="true" /><span><CitedText text={cite(f)} papers={paperMap} /></span></li>)}
                </ul>
              </div>
            )}
            <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-3 text-[13px] text-ink-muted">
              {t.year_range && <span>{t.year_range[0]}–{t.year_range[1]}</span>}
              {refsFor(t.key_paper_ids).length > 0 && <span className="flex items-center">Key papers <RefBadges refs={refsFor(t.key_paper_ids).slice(0, 6)} papers={paperMap} /></span>}
            </div>
            {t.top_authors.length > 0 && <div className="flex flex-wrap gap-1.5">{t.top_authors.slice(0, 5).map((a) => <span key={a} className="chip">{a}</span>)}</div>}
          </article>
        ))}
      </div>
    </div>
  );
}
