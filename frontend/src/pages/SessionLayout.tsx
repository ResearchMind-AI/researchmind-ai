import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CheckCircle2, Layers, MessageSquare, PenLine, RefreshCw, Share2, Trash2 } from "lucide-react";
import { api, analyseUrl, streamSSE, type AnalyseEvent } from "../api";
import type { Discovery, Paper, PartnerContext, Screening, SessionInfo } from "../types";
import type { HandedQuestion } from "../components/ChatThread";
import PartnerPanel from "../components/PartnerPanel";
import { ErrorNote, PageLoading, Spinner, useToast } from "../components/ui";

export interface SessionCtx {
  sid: number;
  session: SessionInfo & { discovery: Discovery | null; screening: Screening };
  papers: Paper[];
  kept: Paper[];
  paperMap: Map<number, Paper>;
  running: boolean;
  runAnalysis: () => void;
  /** Open the research partner, optionally about something specific and with a question to ask. */
  openPartner: (ctx?: PartnerContext, question?: string) => void;
  /** What the current page is about (a gap, a section); the partner follows it while open. */
  setPageContext: (ctx: PartnerContext | null) => void;
}
export const useSession = () => useOutletContext<SessionCtx>();

function Progress({ lines, error, onClose }: { lines: string[]; error: string | null; onClose: () => void }) {
  const done = !error && lines[lines.length - 1] === "__done__";
  const shown = lines.filter((l) => l !== "__done__");
  if (done) {
    const added = shown.find((l) => /^Added \d+ papers?/.test(l));
    return (
      <div className="card flex items-center gap-2.5 border-teal-line bg-teal-wash px-5 py-3" role="status">
        <CheckCircle2 size={18} className="flex-none text-teal" aria-hidden="true" />
        <span className="font-semibold">Analysis complete</span>
        {added && <span className="text-sm text-ink-muted">· {added.replace(/\.$/, "")}, themes and gaps updated</span>}
        <button className="btn btn-sm btn-ghost ml-auto" onClick={onClose}>Dismiss</button>
      </div>
    );
  }
  return (
    <div className={`card flex flex-col gap-3 p-5 ${error ? "border-[#F5C2C0]" : "border-teal-line bg-teal-wash"}`} role="status" aria-live="polite">
      <div className="flex items-center gap-2.5 font-semibold">
        {error ? <span className="text-[#7F1D1D]">Analysis stopped</span>
          : <><Spinner />Analysing your topic…</>}
        {error && <button className="btn btn-sm btn-ghost ml-auto" onClick={onClose}>Dismiss</button>}
      </div>
      <ol className="flex flex-col gap-1 text-[13px] text-ink-muted">
        {shown.map((l, i) => (
          <li key={i} className="flex items-center gap-2">
            {i < shown.length - 1 ? <CheckCircle2 size={14} className="flex-none text-teal" aria-hidden="true" />
              : error ? <span className="h-3.5 w-3.5" /> : <span className="pulse h-2 w-2 flex-none rounded-full bg-teal" aria-hidden="true" />}
            {l}
          </li>
        ))}
      </ol>
      {error && <div className="text-sm text-[#7F1D1D]">{error}</div>}
    </div>
  );
}

export default function SessionLayout() {
  const sid = Number(useParams().sid);
  const qc = useQueryClient();
  const toast = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const session = useQuery({ queryKey: ["session", sid], queryFn: () => api.session(sid) });
  const papers = useQuery({ queryKey: ["papers", sid], queryFn: () => api.papers(sid) });
  const gaps = useQuery({ queryKey: ["gaps", sid], queryFn: () => api.gaps(sid) });
  const [lines, setLines] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = !!lines && !error && lines[lines.length - 1] !== "__done__";
  const abort = useRef<AbortController | null>(null);

  // Research partner panel
  const [partnerOpen, setPartnerOpen] = useState(() => { try { return localStorage.getItem("rm.partner") === "1"; } catch { return false; } });
  const [pageCtx, setPageCtx] = useState<PartnerContext | null>(null);
  const [explicitCtx, setExplicitCtx] = useState<PartnerContext | null>(null);
  const [cleared, setCleared] = useState(false);
  const [handed, setHanded] = useState<HandedQuestion | null>(null);
  const setOpen = useCallback((v: boolean) => {
    setPartnerOpen(v);
    try { localStorage.setItem("rm.partner", v ? "1" : "0"); } catch { /* private mode */ }
  }, []);
  const openPartner = useCallback((ctx?: PartnerContext, question?: string) => {
    setExplicitCtx(ctx ?? null); setCleared(false); setOpen(true);
    if (question) setHanded({ q: question, nonce: Date.now() });
  }, [setOpen]);
  const setPageContext = useCallback((ctx: PartnerContext | null) => {
    setPageCtx((prev) => (JSON.stringify(prev) === JSON.stringify(ctx) ? prev : ctx));
    setExplicitCtx(null); setCleared(false);
  }, []);
  const partnerCtx: PartnerContext = cleared ? { kind: "session" } : explicitCtx ?? pageCtx ?? { kind: "session" };
  // Leave room for the docked panel on wide screens.
  useEffect(() => {
    document.documentElement.style.setProperty("--rm-partner", partnerOpen ? "432px" : "0px");
    return () => { document.documentElement.style.setProperty("--rm-partner", "0px"); };
  }, [partnerOpen]);

  const runAnalysis = useCallback(() => {
    if (running) return;
    setLines([]);
    setError(null);
    abort.current = new AbortController();
    streamSSE<AnalyseEvent>(analyseUrl(sid), {}, (e) => {
      if (e.type === "progress") setLines((l) => [...(l ?? []), e.message]);
      else if (e.type === "error") setError(e.message);
      else if (e.type === "done") setLines((l) => [...(l ?? []), "__done__"]);
    }, abort.current.signal)
      .catch((e: Error) => { if (e.name !== "AbortError") setError(e.message); })
      .finally(async () => {
        // Cancel fetches that started before the analysis finished; otherwise they
        // would be reused by the refetch and show stale (empty) results.
        for (const k of ["session", "papers", "analysis", "gaps", "writing"]) {
          await qc.cancelQueries({ queryKey: [k, sid] });
          qc.invalidateQueries({ queryKey: [k, sid] });
        }
        qc.invalidateQueries({ queryKey: ["sessions"] });
      });
  }, [sid, running, qc]);

  // Auto-run when arriving from "New research session".
  const started = useRef(false);
  useEffect(() => {
    if ((location.state as { run?: boolean } | null)?.run && !started.current) {
      started.current = true;
      navigate(location.pathname, { replace: true, state: null });
      runAnalysis();
    }
  }, [location, navigate, runAnalysis]);
  useEffect(() => () => abort.current?.abort(), [sid]);

  // All papers (removed ones too) so citation numbers always resolve; `kept` drives counts.
  const paperMap = useMemo(() => new Map((papers.data ?? []).map((p) => [p.n, p])), [papers.data]);
  const kept = useMemo(() => (papers.data ?? []).filter((p) => p.status === "kept"), [papers.data]);

  if (session.isLoading) return <PageLoading />;
  if (session.error || !session.data) return <ErrorNote error={session.error} />;
  const s = session.data;

  async function remove() {
    if (!window.confirm(`Delete "${s.title}"? This removes its papers, gaps and writing for everyone.`)) return;
    try {
      await api.deleteSession(sid);
      qc.invalidateQueries({ queryKey: ["sessions"] });
      navigate("/");
    } catch (e) { toast((e as Error).message, "error"); }
  }

  const tracked = (gaps.data ?? []).filter((g) => (g.pinned || g.source === "user") && g.status !== "dropped").length;
  const words = s.words ?? 0;
  const tabs = [
    { to: "papers", label: "Papers", icon: BookOpen, count: `${papers.data ? kept.length : s.paper_count} kept` },
    { to: "explore", label: "Explore", icon: Layers, count: `${s.theme_count} themes · ${tracked} gap${tracked === 1 ? "" : "s"} tracked` },
    { to: "write", label: "Write", icon: PenLine, count: `${words} words` },
  ];
  const ctx: SessionCtx = { sid, session: s, papers: papers.data ?? [], kept, paperMap, running, runAnalysis, openPartner, setPageContext };

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 max-w-[720px] flex-col gap-2">
          <div className="text-[13px] text-ink-muted">Research session</div>
          <h1 className="h-serif text-[28px] leading-tight md:text-[32px]">{s.title}</h1>
          {s.topic && s.topic !== s.title && <p className="text-ink-muted">{s.topic}</p>}
          <div className="flex flex-wrap gap-1.5">
            {s.discovery?.domain && <span className="chip">{s.discovery.domain}</span>}
            {s.role !== "owner" && <span className="chip chip-blue">You are a {s.role}</span>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {s.can_manage && <NavLink to="share" className="btn no-underline"><Share2 size={16} aria-hidden="true" />Share</NavLink>}
          <button className={`btn ${partnerOpen ? "border-teal text-teal-ink" : ""}`} aria-pressed={partnerOpen} onClick={() => setOpen(!partnerOpen)}>
            <MessageSquare size={16} aria-hidden="true" />Research partner
          </button>
          {s.can_edit && (
            <button className="btn btn-primary" onClick={runAnalysis} disabled={running}>
              {running ? <Spinner /> : <RefreshCw size={16} aria-hidden="true" />}{s.paper_count ? "Find more papers" : "Find papers"}
            </button>
          )}
          {s.role === "owner" && <button className="btn btn-ghost" onClick={remove} aria-label="Delete session" title="Delete session"><Trash2 size={16} /></button>}
        </div>
      </header>

      {lines && <Progress lines={lines} error={error} onClose={() => { setLines(null); setError(null); }} />}

      <nav className="flex flex-wrap gap-1 rounded-xl border border-line bg-white p-[5px]" aria-label="Session views">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to}
            className={({ isActive }) => `flex h-[38px] items-center gap-2 rounded-lg px-3.5 font-semibold no-underline ${isActive ? "bg-navy text-white" : "text-ink-2 hover:bg-ground hover:text-ink"}`}>
            {({ isActive }) => <><t.icon size={16} aria-hidden="true" />{t.label}<span className={`rounded-full px-[7px] text-xs font-semibold ${isActive ? "bg-navy-3 text-white" : "bg-chip text-ink-muted"}`}>{t.count}</span></>}
          </NavLink>
        ))}
      </nav>

      <Outlet context={ctx} />

      {partnerOpen && (
        <div className="fixed inset-0 z-30 border-l border-line shadow-2xl sm:left-auto sm:w-[420px]">
          <PartnerPanel sid={sid} ctx={partnerCtx} handed={handed} paperMap={paperMap} canAsk={s.can_edit}
            onClearContext={() => setCleared(true)} onClose={() => setOpen(false)} onAsk={(c, q) => openPartner(c, q)} />
        </div>
      )}
    </div>
  );
}
