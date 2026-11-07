import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, Check, CheckCircle2, ChevronDown, Download, Lightbulb, ListChecks, MessageSquare, PenLine, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api } from "../api";
import type { Feedback, Section, Writing } from "../types";
import { CitedText, Empty, ErrorNote, PageLoading, RefBadges, Spinner, useToast } from "../components/ui";
import { useSession } from "./SessionLayout";
import { ApiError } from "../api";
import { Avatar, CommentThreads, HistoryButton, ProposalBanner, useComments, who } from "../components/collab";
import { Diff } from "../components/diff";

const countWords = (t: string) => (t.trim() ? t.trim().split(/\s+/).length : 0);

function useAutosave(save: (v: string) => Promise<unknown>, value: string, dirty: boolean, delay = 1200) {
  const latest = useRef({ save, value, dirty });
  latest.current = { save, value, dirty };
  useEffect(() => {
    if (!dirty) return;
    const t = setTimeout(() => { latest.current.save(latest.current.value); }, delay);
    return () => clearTimeout(t);
  }, [value, dirty, delay]);
  // Flush pending edits when leaving the section or page.
  useEffect(() => () => { if (latest.current.dirty) latest.current.save(latest.current.value); }, []);
}

function TitleField({ sid, title, canEdit }: { sid: number; title: string; canEdit: boolean }) {
  const [val, setVal] = useState(title);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { if (!dirty) setVal(title); }, [title, dirty]);
  useAutosave(async (v) => { if (v.trim()) { await api.setTitle(sid, v.trim()); setDirty(false); } }, val, dirty);
  return (
    <div>
      <label className="sr-only" htmlFor="review-title">Review title</label>
      <input id="review-title" readOnly={!canEdit} value={val} onChange={(e) => { setVal(e.target.value); setDirty(true); }}
        className="h-serif w-full rounded-lg border border-transparent bg-transparent px-2 py-1 text-[24px] outline-none hover:border-line focus:border-teal focus:bg-white" />
    </div>
  );
}

function FeedbackCard({ f, paperMap }: { f: Feedback; paperMap: ReturnType<typeof useSession>["paperMap"] }) {
  const groups = [
    { key: "cite", title: "Needs a citation", icon: AlertTriangle, tone: "border-amber-line bg-amber-wash", items: [
      ...f.uncited_claims.map((c) => <><span className="font-serif italic">“{c.sentence}”</span><span className="block text-[13px] text-ink-muted">{c.why}{c.suggested_refs.length > 0 && <> Try <RefBadges refs={c.suggested_refs} papers={paperMap} /></>}</span></>),
      ...f.citation_issues.map((c) => <><span className="font-serif italic">“{c.sentence}”</span><span className="block text-[13px] text-ink-muted">[{c.ref}] {c.issue}</span></>),
      ...(f.removed_refs ?? []).map((r) => <>You cite <RefBadges refs={[r.n]} papers={paperMap} />, which you removed{r.reason ? ` (${r.reason.replace(/_/g, " ")})` : ""}. Restore it in Papers, or cite another paper.</>),
      ...(f.unknown_refs.length ? [<>You cite {f.unknown_refs.map((n) => `[${n}]`).join(" ")}, which {f.unknown_refs.length === 1 ? "isn't a paper" : "aren't papers"} in this session.</>] : []),
    ] },
    { key: "missing", title: "Not covered yet", icon: ListChecks, tone: "border-line bg-ground", items: f.missing_points.map((m) => <CitedText text={m} papers={paperMap} />) },
    { key: "good", title: "Working well", icon: CheckCircle2, tone: "border-teal-line bg-teal-wash", items: f.strengths.map((s) => <CitedText text={s} papers={paperMap} />) },
  ];
  return (
    <section className="card flex flex-col gap-4 p-5" aria-label="Feedback on this section">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold">Feedback on your draft</div>
        <span className="text-[13px] text-ink-muted">{f.words} words{f.target_words ? ` · aim for about ${f.target_words}` : ""}</span>
      </div>
      {f.summary && <p className="text-sm text-ink-2">{f.summary}</p>}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
        {groups.map(({ key, title, icon: Icon, tone, items }) => (
          <div key={key} className={`flex flex-col gap-2 rounded-xl border p-3.5 ${tone}`}>
            <div className="flex items-center gap-2 text-sm font-semibold"><Icon size={16} aria-hidden="true" />{title} <span className="font-normal text-ink-muted">· {items.length}</span></div>
            {items.length === 0 ? <div className="text-[13px] text-ink-muted">Nothing here.</div>
              : <ul className="flex flex-col gap-2 text-sm">{items.map((it, i) => <li key={i}>{it}</li>)}</ul>}
          </div>
        ))}
      </div>
      <div className="text-xs text-ink-muted">Feedback only. ResearchMind doesn't rewrite your text.</div>
    </section>
  );
}

function SectionEditor({ s, canEdit }: { s: Section; canEdit: boolean }) {
  const { sid, paperMap, openPartner, collab } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const comments = useComments(sid);
  const [text, setText] = useState(s.user_text ?? "");
  const [heading, setHeading] = useState(s.heading);
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  // Working together: each section belongs to whoever started it; others suggest edits.
  const ownedByOther = collab.collaborative && !!s.owner_id && s.owner_id !== collab.me;
  const editable = canEdit && !ownedByOther;
  const owner = collab.person(s.owner_id);
  const versionRef = useRef(s.version ?? 0);
  const [conflict, setConflict] = useState<{ theirs: string; version: number; by: string } | null>(null);
  const [suggesting, setSuggesting] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [quote, setQuote] = useState<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const pending = collab.suggestions.filter((x) => x.section_id === s.id);
  const forMe = !ownedByOther ? pending.filter((x) => x.user_id !== collab.me) : [];
  const myPending = pending.filter((x) => x.user_id === collab.me);
  const delProposal = collab.proposalFor("delete_section", s.id);
  const threads = (comments.data ?? []).filter((t) => t.target_type === "section" && t.target_id === s.id);

  const writeCache = (sec: Section) => qc.setQueryData<Writing>(["writing", sid], (w) => w && { ...w, sections: w.sections.map((x) => (x.id === sec.id ? { ...x, ...sec } : x)) });
  const save = async (v: string, h = heading, base = versionRef.current) => {
    if (!editable) return;
    setStatus("saving");
    try {
      const sec = await api.saveSection(sid, s.id, v, h.trim() || s.heading, base);
      versionRef.current = sec.version;
      writeCache(sec); setDirty(false); setStatus("saved"); setConflict(null);
      qc.invalidateQueries({ queryKey: ["session", sid] });
    } catch (e) {
      setStatus("idle");
      if (e instanceof ApiError && e.status === 409 && e.data) {
        // Someone saved this section after we loaded it: never overwrite silently.
        setDirty(false);
        setConflict({ theirs: String(e.data.current_text ?? ""), version: Number(e.data.version ?? 0), by: String(e.data.updated_by_name ?? "Someone") });
      } else toast((e as Error).message, "error");
    }
  };
  async function sendSuggestion() {
    if (suggesting == null) return;
    try {
      await api.suggestEdit(sid, s.id, suggesting, note || undefined);
      setSuggesting(null); setNote("");
      qc.invalidateQueries({ queryKey: ["collab", sid] });
      toast(`Suggested. ${owner?.name.split(" ")[0] ?? "The writer"} can accept or reject it.`);
    } catch (e) { toast((e as Error).message, "error"); }
  }
  async function decideSuggestion(id: number, d: "accept" | "reject" | "withdraw", newText?: string) {
    try {
      await api.decideSuggestion(sid, id, d);
      if (d === "accept" && newText != null) { setText(newText); setDirty(false); versionRef.current += 1; }
      for (const k of ["collab", "writing", "whatsnew", "session"]) qc.invalidateQueries({ queryKey: [k, sid] });
      toast(d === "accept" ? "Edit accepted" : d === "reject" ? "Edit rejected" : "Suggestion withdrawn");
    } catch (e) { toast((e as Error).message, "error"); }
  }
  function commentOnSelection() {
    const el = textRef.current;
    const sel = el ? el.value.slice(el.selectionStart, el.selectionEnd).trim() : "";
    setQuote(sel ? sel.slice(0, 300) : null);
    document.getElementById(`c-section-${s.id}`)?.focus();
  }
  useAutosave((v) => save(v), text, dirty);

  const check = useMutation({
    mutationFn: async () => { if (dirty) await save(text); return api.checkSection(sid, s.id); },
    onSuccess: (feedback) => writeCache({ ...s, user_text: text, feedback }),
    onError: (e: Error) => toast(e.message, "error"),
  });

  const g = s.guidance;
  const words = countWords(text);
  const target = g?.target_words ?? null;

  return (
    <div className="flex flex-col gap-5">
      {g && (
        <section className="card flex flex-col gap-4 p-5" aria-label="Writing guide">
          <div className="flex items-center gap-2 font-semibold"><Lightbulb size={17} className="text-amber" aria-hidden="true" />What to cover in this section</div>
          {g.points.length > 0 && (
            <ul className="flex flex-col gap-2 text-[15px]">
              {g.points.map((p, i) => <li key={i} className="flex gap-2.5"><span className="mt-[9px] h-1.5 w-1.5 flex-none rounded-full bg-teal" aria-hidden="true" /><span>{p.text}<RefBadges refs={p.refs} papers={paperMap} /></span></li>)}
            </ul>
          )}
          {(g.agreements.length > 0 || g.disagreements.length > 0 || g.questions.length > 0) && (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
              {([["Where studies agree", g.agreements, "bg-teal-wash border-teal-line"], ["Where they disagree", g.disagreements, "bg-amber-wash border-amber-line"], ["Questions to answer", g.questions, "bg-ground border-line"]] as const)
                .filter(([, items]) => items.length).map(([label, items, tone]) => (
                  <div key={label} className={`flex flex-col gap-1.5 rounded-xl border p-3.5 ${tone}`}>
                    <div className="text-[13px] font-semibold">{label}</div>
                    <ul className="flex flex-col gap-1.5 text-sm">{items.map((x, i) => <li key={i}><CitedText text={x} papers={paperMap} /></li>)}</ul>
                  </div>
                ))}
            </div>
          )}
        </section>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="sr-only" htmlFor={`heading-${s.id}`}>Section heading</label>
          <input id={`heading-${s.id}`} readOnly={!editable} value={heading}
            onChange={(e) => setHeading(e.target.value)} onBlur={() => heading.trim() && heading !== s.heading && save(text, heading)}
            className="h-serif min-w-0 flex-1 rounded-lg border border-transparent bg-transparent px-1 py-0.5 text-[20px] outline-none hover:border-line focus:border-teal focus:bg-white" />
          <span className="flex items-center gap-2 text-[13px] text-ink-muted" aria-live="polite">
            {collab.collaborative && owner && <><Avatar person={owner} size={20} />{s.owner_id === collab.me ? "Your section" : `${owner.name.split(" ")[0]}'s section`} ·</>}
            {words} word{words === 1 ? "" : "s"}{target ? ` of ~${target}` : ""}
            {editable && <> · {status === "saving" ? "Saving…" : dirty ? "Unsaved" : status === "saved" ? "Saved" : "Autosaves"}</>}
            {collab.collaborative && <> · <HistoryButton sid={sid} target={{ type: "section", id: s.id }} title={s.heading} /></>}
          </span>
        </div>
        {target && <div className="h-1 rounded-full bg-chip" aria-hidden="true"><div className="h-1 rounded-full bg-teal transition-all" style={{ width: `${Math.min(100, (words / target) * 100)}%` }} /></div>}
        {delProposal && <ProposalBanner sid={sid} p={delProposal} collab={collab} canEdit={canEdit} what={`the section "${s.heading}"`} />}
        {forMe.map((x) => (
          <div key={x.id} className="flex flex-col gap-2.5 rounded-xl border border-[#F5C9A8] bg-[#FFF7F1] p-3.5">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Avatar person={collab.person(x.user_id)} size={24} />
              <span className="flex-1"><b>{x.user_name}</b> suggested an edit. Your text only changes if you accept.{x.note && <span className="block text-ink-2">“{x.note}”</span>}</span>
              <button className="btn btn-sm btn-primary" onClick={() => decideSuggestion(x.id, "accept", x.new_text)}>Accept</button>
              <button className="btn btn-sm" onClick={() => decideSuggestion(x.id, "reject")}>Reject</button>
            </div>
            <div className="rounded-lg bg-white px-4 py-3 font-serif text-[16px] leading-[1.7]"><Diff from={x.base_text} to={x.new_text} color={collab.person(x.user_id)?.color} /></div>
            {x.base_text !== text && <div className="text-xs text-[#9A3412]">You've changed the section since this was suggested, so it may not apply cleanly.</div>}
          </div>
        ))}
        {conflict && (
          <div className="flex flex-col gap-3 rounded-xl border border-[#F5C9A8] bg-[#FFF7F1] p-4" role="alert">
            <div className="font-semibold">{conflict.by} changed this section while you were editing.</div>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3">
              <div><div className="sub mb-1">Their version</div><div className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-white p-3 font-serif text-[15px]">{conflict.theirs || "(empty)"}</div></div>
              <div><div className="sub mb-1">Yours</div><div className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-white p-3 font-serif text-[15px]">{text || "(empty)"}</div></div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-sm" onClick={() => { setText(conflict.theirs); versionRef.current = conflict.version; setConflict(null); setDirty(false); }}>Use their version</button>
              <button className="btn btn-sm btn-primary" onClick={() => save(text, heading, conflict.version)}>Keep mine</button>
            </div>
          </div>
        )}
        {ownedByOther && canEdit && suggesting == null && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white px-4 py-3 text-sm">
            <span className="flex-1">This section is <b>{owner?.name ?? "someone else"}'s</b>. Suggest an edit and they can accept or reject it.</span>
            <button className="btn btn-sm btn-primary" onClick={() => setSuggesting(text)}>Suggest an edit</button>
          </div>
        )}
        {myPending.map((x) => (
          <div key={x.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-ground px-4 py-2.5 text-sm">
            <span className="flex-1">Your suggested edit is waiting for {who(collab, s.owner_id)}.</span>
            <button className="btn btn-sm" onClick={() => decideSuggestion(x.id, "withdraw")}>Withdraw</button>
          </div>
        ))}
        <label className="sr-only" htmlFor={`text-${s.id}`}>Your text for {s.heading}</label>
        {suggesting != null ? (
          <div className="flex flex-col gap-2">
            <textarea id={`text-${s.id}`} value={suggesting} onChange={(e) => setSuggesting(e.target.value)} autoFocus
              className="textarea min-h-[340px] border-[#F5C9A8] px-5 py-4 font-serif text-[17px] leading-[1.7]" />
            <label className="sr-only" htmlFor={`note-${s.id}`}>Note for the writer</label>
            <input id={`note-${s.id}`} className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why? (optional), e.g. Give the numbers" />
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn btn-primary" onClick={sendSuggestion} disabled={suggesting.trim() === text.trim()}>Send suggestion</button>
              <button className="btn" onClick={() => setSuggesting(null)}>Cancel</button>
              <span className="text-[13px] text-ink-muted">They'll see your changes highlighted.</span>
            </div>
          </div>
        ) : (
          <textarea id={`text-${s.id}`} ref={textRef} readOnly={!editable} value={text} onChange={(e) => { setText(e.target.value); setDirty(true); }}
            placeholder={editable ? "Write this section in your own words. Cite papers by number, like [3] or [4][9]." : "Nothing written yet."}
            className={`textarea min-h-[340px] px-5 py-4 font-serif text-[17px] leading-[1.7] ${editable ? "" : "bg-ground"}`} />
        )}
        {canEdit && suggesting == null && (
          <div className="flex flex-wrap items-center gap-2">
            {editable && <button className="btn btn-primary" onClick={() => check.mutate()} disabled={check.isPending || words < 15}>
              {check.isPending ? <Spinner /> : <Check size={16} aria-hidden="true" />}Save and check
            </button>}
            <button className="btn" onClick={async () => { if (dirty) await save(text); openPartner({ kind: "section", id: s.id, heading: s.heading }); }}>
              <MessageSquare size={16} aria-hidden="true" />Ask about this section
            </button>
            {collab.collaborative && <button className="btn" onClick={commentOnSelection}>Comment on selection</button>}
            {words < 15 && <span className="text-[13px] text-ink-muted">Write at least a few sentences to get feedback.</span>}
          </div>
        )}
      </section>

      {collab.collaborative && (
        <section className="card flex flex-col gap-3 p-5" aria-label="Comments on this section">
          <div className="font-semibold">Comments{threads.filter((t) => !t.resolved).length ? ` · ${threads.filter((t) => !t.resolved).length} open` : ""}</div>
          <CommentThreads sid={sid} collab={collab} threads={threads} target={{ type: "section", id: s.id }} quote={quote}
            canComment onDone={() => setQuote(null)} />
        </section>
      )}

      {s.feedback && <FeedbackCard f={s.feedback} paperMap={paperMap} />}
    </div>
  );
}

function ExampleDraft({ sid, canEdit }: { sid: number; canEdit: boolean }) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const ex = useQuery({ queryKey: ["example", sid], queryFn: () => api.example(sid), enabled: open });
  const make = useMutation({
    mutationFn: () => api.makeExample(sid),
    onSuccess: (d) => qc.setQueryData(["example", sid], d),
    onError: (e: Error) => toast(e.message, "error"),
  });
  return (
    <section className="card overflow-hidden">
      <button className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span><span className="font-semibold">Example draft</span><span className="block text-[13px] text-ink-muted">AI-written, for reference only. Not included in your export.</span></span>
        <ChevronDown size={18} className={`flex-none transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div className="flex flex-col gap-4 border-t border-line px-5 py-4">
          {ex.isLoading ? <div className="flex items-center gap-2 text-sm text-ink-muted"><Spinner />Loading…</div>
            : ex.data ? (
              <div className="flex flex-col gap-4 font-serif text-[15px] leading-relaxed text-ink-2">
                {ex.data.sections.map((sec, i) => (
                  <div key={i} className="flex flex-col gap-2"><h4 className="text-[17px] font-semibold text-ink">{sec.heading}</h4>{sec.paragraphs.map((p, j) => <p key={j}>{p}</p>)}</div>
                ))}
                {ex.data.references.length > 0 && <details className="font-sans text-sm"><summary className="cursor-pointer font-semibold text-teal">References ({ex.data.references.length})</summary><ol className="mt-2 flex list-decimal flex-col gap-1 pl-5 text-[13px]">{ex.data.references.map((r, i) => <li key={i}>{r}</li>)}</ol></details>}
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-ink-muted">
                <span>See how the evidence could be written up, then write your own version.</span>
                {canEdit && <button className="btn btn-sm" onClick={() => make.mutate()} disabled={make.isPending}>{make.isPending ? <><Spinner />Writing… about a minute</> : "Generate example"}</button>}
              </div>
            )}
        </div>
      )}
    </section>
  );
}

export default function WriteView() {
  const { sid, session, papers, setPageContext, collab } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [style, setStyle] = useState("APA");
  const writing = useQuery({ queryKey: ["writing", sid], queryFn: () => api.writing(sid) });
  const canEdit = session.can_edit;
  const refresh = () => qc.invalidateQueries({ queryKey: ["writing", sid] });
  const outline = useMutation({ mutationFn: () => api.outline(sid), onSuccess: refresh, onError: (e: Error) => toast(e.message, "error") });
  // When papers, key papers or tracked gaps change, the guide's suggestions update by themselves.
  // Only the suggestions change: headings, order and the researcher's text are never touched.
  const [guideNote, setGuideNote] = useState<string | null>(null);
  const guideRefresh = useMutation({
    mutationFn: () => api.refreshGuidance(sid),
    onSuccess: (r) => {
      qc.setQueryData<Writing>(["writing", sid], (w) => w && { ...w, sections: r.sections, guide_changes: null });
      setGuideNote(r.summary ? `Guide updated: ${r.summary}. Your writing wasn't changed.` : "Guide updated.");
    },
    onError: () => setGuideNote(null),
  });
  const guideRan = useRef(false);
  // The research partner follows the section being written.
  const sel = writing.data?.sections.find((x) => String(x.id) === params.get("section")) ?? writing.data?.sections[0];
  useEffect(() => {
    setPageContext(sel ? { kind: "section", id: sel.id, heading: sel.heading } : null);
    return () => setPageContext(null);
  }, [sel?.id, sel?.heading, setPageContext]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (writing.data?.guide_changes && canEdit && !guideRan.current) { guideRan.current = true; guideRefresh.mutate(); }
  }, [writing.data, canEdit, guideRefresh]);
  const addSection = useMutation({
    mutationFn: (heading: string) => api.addSection(sid, heading),
    onSuccess: (s) => { refresh(); setParams({ section: String(s.id) }); },
    onError: (e: Error) => toast(e.message, "error"),
  });

  if (writing.isLoading) return <PageLoading />;
  if (writing.error || !writing.data) return <ErrorNote error={writing.error} />;
  const { sections, title } = writing.data;

  if (!sections.length) {
    return (
      <Empty icon={<PenLine size={22} />} title="Write your literature review">
        <div className="flex flex-col items-center gap-3">
          <span>ResearchMind suggests an outline and, for each section, the points to cover and which papers support them. You do the writing.</span>
          {canEdit && (papers.length
            ? <button className="btn btn-primary" onClick={() => outline.mutate()} disabled={outline.isPending}>{outline.isPending ? <><Spinner />Building your guide… about a minute</> : "Suggest an outline"}</button>
            : <span className="text-[13px]">Find papers first.</span>)}
        </div>
      </Empty>
    );
  }

  const selected = sections.find((s) => String(s.id) === params.get("section")) ?? sections[0];
  const total = sections.reduce((n, s) => n + (s.words || 0), 0);

  async function move(s: Section, d: -1 | 1) {
    try { const list = await api.moveSection(sid, s.id, d); qc.setQueryData<Writing>(["writing", sid], (w) => w && { ...w, sections: list }); }
    catch (e) { toast((e as Error).message, "error"); }
  }
  async function remove(s: Section) {
    if (!collab.collaborative && !window.confirm(`Delete the section "${s.heading}" and what you've written in it?`)) return;
    try {
      const r = await api.deleteSection(sid, s.id);
      if (r?.proposal) { qc.invalidateQueries({ queryKey: ["collab", sid] }); toast("Proposed. Someone else needs to approve deleting it."); return; }
      setParams({}); refresh();
    } catch (e) { toast((e as Error).message, "error"); }
  }
  function newSection() {
    const h = window.prompt("Heading for the new section");
    if (h?.trim()) addSection.mutate(h.trim());
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1"><TitleField sid={sid} title={title} canEdit={canEdit} /></div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="cite-style">Citation style</label>
          <select id="cite-style" className="input h-10 w-auto py-0" value={style} onChange={(e) => setStyle(e.target.value)}>
            <option value="APA">APA</option><option value="IEEE">IEEE</option>
          </select>
          {total > 0 ? <>
            <a className="btn no-underline" href={api.exportUrl(sid, style, "docx")} download><Download size={16} aria-hidden="true" />Word</a>
            <a className="btn no-underline" href={api.exportUrl(sid, style, "pdf")} download><Download size={16} aria-hidden="true" />PDF</a>
          </> : <span className="text-[13px] text-ink-muted">Export unlocks once you've written something</span>}
        </div>
      </div>

      <p className="-mt-2 text-sm text-ink-muted"><b className="text-ink">Write</b> your literature review section by section. The guide suggests what to cover and which papers support it; you do the writing.</p>
      {(guideRefresh.isPending || guideNote) && (
        <div className="flex items-center gap-2 text-[13px] text-ink-muted" role="status">
          {guideRefresh.isPending ? <><Spinner />Updating the guide for your latest changes…</> : <><RefreshCw size={14} className="text-teal" aria-hidden="true" />{guideNote}</>}
        </div>
      )}
      <div className="grid items-start gap-5 lg:grid-cols-[280px_1fr]">
        <aside className="card flex flex-col gap-1 p-3 lg:sticky lg:top-6" aria-label="Outline">
          <div className="flex items-center justify-between px-2 pb-1.5 pt-1"><span className="sub">Outline</span><span className="text-xs text-ink-muted">{total} words</span></div>
          {sections.map((s, i) => {
            const target = s.guidance?.target_words;
            const done = s.words > 0 && (!target || s.words >= target * 0.6);
            const active = s.id === selected.id;
            return (
              <div key={s.id} className={`group flex items-center gap-1 rounded-lg ${active ? "bg-teal-soft" : "hover:bg-ground"}`}>
                <button className="flex min-w-0 flex-1 items-center gap-2.5 px-2.5 py-2 text-left" onClick={() => setParams({ section: String(s.id) })} aria-current={active ? "true" : undefined}>
                  <span className={`flex h-5 w-5 flex-none items-center justify-center rounded-full border text-[11px] ${done ? "border-teal bg-teal text-white" : s.words ? "border-teal text-teal" : "border-line text-ink-muted"}`} aria-hidden="true">
                    {done ? <Check size={12} /> : i + 1}
                  </span>
                  <span className="min-w-0 flex-1"><span className={`block truncate text-sm ${active ? "font-semibold text-teal-ink" : ""}`}>{s.heading}</span>
                    <span className="text-xs text-ink-muted">{s.words}{target ? ` / ${target}` : ""} words</span></span>
                  {collab.collaborative && (s.owner_id ? <Avatar person={collab.person(s.owner_id)} size={20} />
                    : <span className="h-5 w-5 flex-none rounded-full border-2 border-dashed border-line" title="Not started" aria-label="Not started" />)}
                  {collab.suggestions.some((x) => x.section_id === s.id) && s.owner_id === collab.me && <span className="h-2 w-2 flex-none rounded-full bg-[#C2410C]" aria-label="Suggested edit waiting" />}
                </button>
                {canEdit && active && (
                  <span className="flex flex-none pr-1">
                    <button className="rounded p-1 text-ink-muted hover:text-ink disabled:opacity-30" disabled={i === 0} onClick={() => move(s, -1)} aria-label="Move up"><ArrowUp size={14} /></button>
                    <button className="rounded p-1 text-ink-muted hover:text-ink disabled:opacity-30" disabled={i === sections.length - 1} onClick={() => move(s, 1)} aria-label="Move down"><ArrowDown size={14} /></button>
                    <button className="rounded p-1 text-ink-muted hover:text-[#B91C1C]" onClick={() => remove(s)} aria-label="Delete section"><Trash2 size={14} /></button>
                  </span>
                )}
              </div>
            );
          })}
          {canEdit && <button className="mt-1 flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-semibold text-teal hover:bg-ground" onClick={newSection}><Plus size={15} aria-hidden="true" />Add section</button>}
          {collab.collaborative && <div className="border-t border-line px-2.5 pt-2 text-xs text-ink-muted">Each section belongs to whoever starts it. Others suggest edits.</div>}
        </aside>
        <div className="flex min-w-0 flex-col gap-5">
          <SectionEditor key={selected.id} s={selected} canEdit={canEdit} />
          <ExampleDraft sid={sid} canEdit={canEdit} />
        </div>
      </div>
    </div>
  );
}
