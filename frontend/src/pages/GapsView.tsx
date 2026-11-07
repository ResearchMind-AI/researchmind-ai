import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";
import { Check, ExternalLink, MessageSquare, Pin, Plus, SearchCheck, Sparkles, Target, Trash2, User as UserIcon } from "lucide-react";
import { api } from "../api";
import type { Gap, GapStatus } from "../types";
import { Empty, ErrorNote, Modal, PageLoading, RefBadges, Spinner, useToast } from "../components/ui";
import { useSession } from "./SessionLayout";
import { CommentsButton, HistoryButton, ProposalBanner, useComments, who } from "../components/collab";

const STATUS: { value: GapStatus; label: string }[] = [
  { value: "open", label: "Open" }, { value: "exploring", label: "Exploring" },
  { value: "promising", label: "Promising" }, { value: "dropped", label: "Dropped" },
];
const VERDICT = {
  open: { label: "Looks open", tone: "bg-teal-soft text-teal-ink border-teal-line", text: "No recent work found that directly addresses this." },
  partially_addressed: { label: "Partly addressed", tone: "bg-amber-soft text-amber-ink border-amber-line", text: "Some recent work touches on this. Narrow the angle." },
  addressed: { label: "Already addressed", tone: "bg-[#FBEFEE] text-[#7F1D1D] border-[#F5C2C0]", text: "Recent work appears to cover this." },
  unknown: { label: "Couldn't tell", tone: "bg-chip text-ink-2 border-line", text: "The novelty search didn't return enough to judge." },
};

function AddGapModal({ sid, onClose }: { sid: number; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [assess, setAssess] = useState(true);
  const add = useMutation({
    mutationFn: () => api.addGap(sid, title.trim(), desc.trim(), assess),
    onSuccess: (g) => { qc.invalidateQueries({ queryKey: ["gaps", sid] }); onClose(); navigate(`/s/${sid}/explore/gaps/${g.id}`); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  function submit(e: FormEvent) { e.preventDefault(); add.mutate(); }
  return (
    <Modal title="Add your own gap" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div><label className="label" htmlFor="gt">Gap in one line</label>
          <input id="gt" className="input" required minLength={5} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. No evaluation of LLM triage tools in rural hospitals" autoFocus /></div>
        <div><label className="label" htmlFor="gd">Why it matters <span className="font-normal text-ink-muted">(optional)</span></label>
          <textarea id="gd" className="textarea min-h-[90px]" value={desc} onChange={(e) => setDesc(e.target.value)} /></div>
        <label className="flex items-start gap-2.5 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-teal" checked={assess} onChange={(e) => setAssess(e.target.checked)} />
          <span><span className="font-semibold">Check it now</span><span className="block text-ink-muted">Finds evidence in your papers and searches recent literature to see if it's already been done. About 20 seconds.</span></span>
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={add.isPending || title.trim().length < 5}>{add.isPending && <Spinner />}{add.isPending && assess ? "Checking…" : "Add gap"}</button>
        </div>
      </form>
    </Modal>
  );
}

function GapItem({ g, sid, active }: { g: Gap; sid: number; active: boolean }) {
  return (
    <Link to={`/s/${sid}/explore/gaps/${g.id}`} aria-current={active ? "page" : undefined}
      className={`flex flex-col gap-1 rounded-xl border px-3.5 py-3 text-ink no-underline ${active ? "border-teal bg-teal-wash" : "border-line bg-white hover:border-teal-line"}`}>
      <span className="flex items-start gap-2">
        {g.pinned && <Pin size={14} className="mt-0.5 flex-none text-amber" aria-label="Tracked" />}
        <span className={`text-sm font-semibold leading-snug ${g.status === "dropped" ? "text-ink-muted line-through" : ""}`}>{g.title}</span>
      </span>
      <span className="flex flex-wrap gap-1.5 text-xs text-ink-muted">
        <span>{STATUS.find((s) => s.value === g.status)?.label}</span>
        {g.assessment && <span>· {VERDICT[g.assessment.novelty.verdict]?.label}</span>}
        {g.gap_type && <span>· {g.gap_type}</span>}
      </span>
    </Link>
  );
}

function Notes({ g, sid, canEdit }: { g: Gap; sid: number; canEdit: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [val, setVal] = useState(g.notes ?? "");
  const [saved, setSaved] = useState(true);
  useEffect(() => { setVal(g.notes ?? ""); setSaved(true); }, [g.id, g.notes]);
  useEffect(() => {
    if (saved) return;
    const t = setTimeout(async () => {
      try { await api.updateGap(sid, g.id, { notes: val }); setSaved(true); qc.invalidateQueries({ queryKey: ["gaps", sid] }); }
      catch (e) { toast((e as Error).message, "error"); }
    }, 900);
    return () => clearTimeout(t);
  }, [val, saved, sid, g.id, qc, toast]);
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between"><label className="sub" htmlFor={`notes-${g.id}`}>Your notes</label>
        {canEdit && <span className="text-xs text-ink-muted">{saved ? "Saved" : "Saving…"}</span>}</div>
      <textarea id={`notes-${g.id}`} className="textarea min-h-[90px] font-serif text-[15px]" readOnly={!canEdit} value={val}
        onChange={(e) => { setVal(e.target.value); setSaved(false); }} placeholder="Ideas, angles, people to talk to…" />
    </section>
  );
}

function GapDetail({ g }: { g: Gap }) {
  const { sid, session, papers, paperMap, openPartner, collab } = useSession();
  const comments = useComments(sid);
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const nById = new Map(papers.map((p) => [p.id, p.n]));
  const refs = g.evidence_paper_ids.map((i) => nById.get(i)).filter((n): n is number => !!n);
  const update = useMutation({
    mutationFn: (patch: Partial<Pick<Gap, "pinned" | "status">>) => api.updateGap(sid, g.id, patch),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["gaps", sid] }); qc.invalidateQueries({ queryKey: ["writing", sid] });
      if ("proposal" in r) { qc.invalidateQueries({ queryKey: ["collab", sid] }); toast("Proposed. Someone else needs to approve it."); }
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const assess = useMutation({
    mutationFn: () => api.assessGap(sid, g.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["gaps", sid] }); qc.invalidateQueries({ queryKey: ["writing", sid] }); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  async function remove() {
    if (!collab.collaborative && !window.confirm("Delete this gap and its discussion?")) return;
    try {
      const r = await api.deleteGap(sid, g.id);
      if (r?.proposal) { qc.invalidateQueries({ queryKey: ["collab", sid] }); toast("Proposed. Someone else needs to approve deleting it."); return; }
      qc.invalidateQueries({ queryKey: ["gaps", sid] }); navigate(`/s/${sid}/explore/gaps`);
    } catch (e) { toast((e as Error).message, "error"); }
  }
  const proposal = collab.proposalFor("untrack_gap", g.id) ?? collab.proposalFor("delete_gap", g.id);
  const a = g.assessment;
  const v = a ? VERDICT[a.novelty.verdict] ?? VERDICT.unknown : null;
  const rq = g.research_question || a?.evidence.research_question;
  const canEdit = session.can_edit;

  return (
    <div className="card flex flex-col gap-5 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap gap-1.5">
            {g.source === "user" ? <span className="chip chip-blue"><UserIcon size={12} aria-hidden="true" />Your gap</span> : <span className="chip chip-teal"><Sparkles size={12} aria-hidden="true" />Suggested by AI</span>}
            {g.gap_type && <span className="chip">{g.gap_type}</span>}
            {g.confidence && <span className="chip">{g.confidence} confidence</span>}
          </div>
          <h2 className="h-serif text-[24px] leading-tight">{g.title}</h2>
          {collab.collaborative && (
            <div className="flex flex-wrap items-center gap-x-3 text-xs text-ink-muted">
              {g.source === "user" && g.created_by && <span>Added by {who(collab, g.created_by)}</span>}
              <HistoryButton sid={sid} target={{ type: "gap", id: g.id }} title={g.title} />
            </div>
          )}
        </div>
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="gap-status">Status</label>
            <select id="gap-status" className="input h-9 w-auto py-0" value={g.status} onChange={(e) => update.mutate({ status: e.target.value as GapStatus })}>
              {STATUS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
            <button className={`btn btn-sm ${g.pinned ? "border-teal-line bg-teal-soft text-teal-ink" : ""}`} aria-pressed={g.pinned}
              title={g.pinned ? "Stop tracking" : "Track this gap"}
              onClick={() => update.mutate({ pinned: !g.pinned }, {
                // Tracking a gap checks it straight away, so the verdict is just there.
                onSuccess: () => { if (!g.pinned && !g.assessment) assess.mutate(); },
              })}>
              {g.pinned ? <><Check size={14} />Tracked</> : <><Pin size={14} />Track this gap</>}
            </button>
            {collab.collaborative && <CommentsButton sid={sid} collab={collab} threads={comments.data ?? []} target={{ type: "gap", id: g.id }} title={g.title} canComment />}
            <button className="btn btn-sm btn-ghost" onClick={remove} aria-label={collab.collaborative ? "Propose deleting this gap" : "Delete gap"} title={collab.collaborative ? "Propose deleting" : "Delete gap"}><Trash2 size={14} /></button>
          </div>
        )}
        {!canEdit && collab.collaborative && <CommentsButton sid={sid} collab={collab} threads={comments.data ?? []} target={{ type: "gap", id: g.id }} title={g.title} canComment />}
      </div>
      {proposal && <ProposalBanner sid={sid} p={proposal} collab={collab} canEdit={canEdit} what={`this gap`} />}

      {g.description && <p className="text-[15px] text-ink-2">{g.description}{refs.length > 0 && <RefBadges refs={refs} papers={paperMap} />}</p>}
      {rq && (
        <section className="rounded-xl border-l-4 border-teal bg-teal-wash px-4 py-3">
          <div className="sub mb-1">Research question</div>
          <p className="h-serif text-[17px]">{rq}</p>
        </section>
      )}

      {a && v ? (
        <section className={`flex flex-col gap-3 rounded-xl border p-4 ${v.tone}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 font-semibold"><SearchCheck size={18} aria-hidden="true" />Novelty check: {v.label}</div>
            <span className="text-xs opacity-80">Checked {new Date(a.checked_at).toLocaleDateString()}{a.novelty.searched ? ` · ${a.novelty.searched} recent papers searched` : ""}</span>
          </div>
          <p className="text-sm">{a.novelty.explanation || v.text}</p>
          {a.novelty.closest.length > 0 && (
            <div className="flex flex-col gap-2 rounded-lg bg-white/70 p-3 text-ink">
              <div className="sub">Closest existing work</div>
              {a.novelty.closest.map((c, i) => (
                <div key={i} className="text-sm">
                  {c.url ? <a href={c.url} target="_blank" rel="noreferrer" className="font-semibold">{c.title}<ExternalLink size={12} className="ml-1 inline" aria-hidden="true" /></a> : <span className="font-semibold">{c.title}</span>}
                  {c.year && <span className="text-ink-muted"> ({c.year})</span>}
                  {c.why && <div className="text-[13px] text-ink-muted">{c.why}</div>}
                </div>
              ))}
            </div>
          )}
          {canEdit && <button className="btn btn-sm self-start bg-white" onClick={() => assess.mutate()} disabled={assess.isPending}>{assess.isPending && <Spinner />}Check again</button>}
        </section>
      ) : canEdit && (
        <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-amber-line bg-amber-wash p-4">
          <div className="text-sm text-amber-text"><span className="font-semibold">Is this gap really open?</span> Check your papers for evidence and search recent literature for existing work.</div>
          <button className="btn btn-sm bg-white" onClick={() => assess.mutate()} disabled={assess.isPending}>{assess.isPending ? <><Spinner />Checking…</> : <><SearchCheck size={14} />Check this gap</>}</button>
        </section>
      )}

      {a && (a.evidence.supporting.length > 0 || a.evidence.contradicting.length > 0) && (
        <section className="flex flex-col gap-3">
          <div className="sub">Evidence in your papers</div>
          {a.evidence.summary && <p className="text-sm text-ink-2">{a.evidence.summary}</p>}
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
            {([["Supports the gap", a.evidence.supporting], ["Cuts against it", a.evidence.contradicting]] as const).map(([label, items]) => items.length > 0 && (
              <div key={label} className="flex flex-col gap-2">
                <div className="text-[13px] font-semibold text-ink-2">{label}</div>
                {items.map((it) => (
                  <div key={it.n} className="flex gap-2 text-sm"><RefBadges refs={[it.n]} papers={paperMap} /><span><span className="font-semibold">{it.title}</span><span className="block text-[13px] text-ink-muted">{it.why}</span></span></div>
                ))}
              </div>
            ))}
          </div>
        </section>
      )}

      <Notes g={g} sid={sid} canEdit={canEdit} />

      <section className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
        <button className="btn" onClick={() => openPartner({ kind: "gap", id: g.id, title: g.title })}>
          <MessageSquare size={16} aria-hidden="true" />Discuss with your research partner
        </button>
        <span className="text-[13px] text-ink-muted">It knows this gap, its check and your notes.</span>
      </section>
    </div>
  );
}

export default function GapsView() {
  const { sid, session, papers, running } = useSession();
  const { gapId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const gaps = useQuery({ queryKey: ["gaps", sid], queryFn: () => api.gaps(sid) });
  const suggest = useMutation({
    mutationFn: () => api.suggestGaps(sid),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["gaps", sid] }); toast("New gap suggestions added"); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  const list = gaps.data ?? [];
  const selected = list.find((g) => String(g.id) === gapId);
  const { setPageContext } = useSession();
  useEffect(() => {
    setPageContext(selected ? { kind: "gap", id: selected.id, title: selected.title } : null);
    return () => setPageContext(null);
  }, [selected?.id, selected?.title, setPageContext]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!gapId && list.length && window.matchMedia("(min-width: 1024px)").matches) {
      const first = list.find((g) => g.pinned) ?? list[0];
      navigate(`/s/${sid}/explore/gaps/${first.id}`, { replace: true });
    }
  }, [gapId, list, navigate, sid]);

  if (gaps.isLoading) return <PageLoading />;
  if (gaps.error) return <ErrorNote error={gaps.error} />;

  const mine = list.filter((g) => g.pinned || g.source === "user");
  const ai = list.filter((g) => !g.pinned && g.source === "ai");

  if (!list.length) {
    return (
      <>
        <Empty icon={<Target size={22} />} title={running ? "Looking for gaps…" : "No gaps yet"}>
          {running ? "Gap suggestions appear after themes are ready." : (
            <div className="flex flex-col items-center gap-3">
              <span>Let ResearchMind suggest gaps from your papers, or add one you've spotted.</span>
              {session.can_edit && <div className="flex gap-2">
                {papers.length > 0 && <button className="btn btn-primary" onClick={() => suggest.mutate()} disabled={suggest.isPending}>{suggest.isPending && <Spinner />}Suggest gaps</button>}
                <button className="btn" onClick={() => setAdding(true)}><Plus size={16} />Add your own</button>
              </div>}
            </div>
          )}
        </Empty>
        {adding && <AddGapModal sid={sid} onClose={() => setAdding(false)} />}
      </>
    );
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]">
      <aside className={`flex flex-col gap-4 ${selected ? "hidden lg:flex" : ""}`} aria-label="Gaps">
        {session.can_edit && <button className="btn btn-primary" onClick={() => setAdding(true)}><Plus size={16} aria-hidden="true" />Add your own gap</button>}
        <div className="flex flex-col gap-2">
          <div className="sub">Tracked · {mine.length}</div>
          {mine.length === 0 && <div className="rounded-xl border border-dashed border-line px-3.5 py-3 text-[13px] text-ink-muted">Track a suggestion or add your own to keep it here.</div>}
          {mine.map((g) => <GapItem key={g.id} g={g} sid={sid} active={g.id === selected?.id} />)}
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div className="sub">Suggested by AI · {ai.length}</div>
            {session.can_edit && <button className="text-[13px] font-semibold text-teal disabled:opacity-50" onClick={() => suggest.mutate()} disabled={suggest.isPending || running}>{suggest.isPending ? "Thinking…" : "Refresh"}</button>}
          </div>
          {ai.map((g) => <GapItem key={g.id} g={g} sid={sid} active={g.id === selected?.id} />)}
        </div>
      </aside>
      <div className={selected ? "" : "hidden lg:block"}>
        {selected ? (
          <div className="flex flex-col gap-3">
            <Link to={`/s/${sid}/explore/gaps`} className="text-sm font-semibold lg:hidden">← All gaps</Link>
            <GapDetail g={selected} />
          </div>
        ) : <Empty icon={<Target size={22} />} title="Pick a gap">Select a gap on the left to see its evidence and discuss it.</Empty>}
      </div>
      {adding && <AddGapModal sid={sid} onClose={() => setAdding(false)} />}
    </div>
  );
}
