// Working together: people, proposals, comments, history and "What's new".
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, MessageCircle, X } from "lucide-react";
import { api } from "../api";
import type { CollabMember, CommentThread, Proposal, WhatsNew } from "../types";
import { Modal, Spinner, useToast } from "./ui";

// Distinct in lightness as well as hue, so people can be told apart without colour vision.
const COLORS = ["#0F766E", "#C2410C", "#1D4ED8", "#7C3AED", "#BE185D", "#4D7C0F"];

export function useCollab(sid: number) {
  const q = useQuery({ queryKey: ["collab", sid], queryFn: () => api.collab(sid), refetchInterval: 20_000, staleTime: 10_000 });
  return useMemo(() => {
    const st = q.data;
    const members = st?.members ?? [];
    const byId = new Map(members.map((m, i) => [m.id, { ...m, color: COLORS[i % COLORS.length] }]));
    return {
      loaded: !!st,
      me: st?.me ?? 0,
      collaborative: !!st?.collaborative,
      members: [...byId.values()],
      person: (id: number | null | undefined) => (id ? byId.get(id) : undefined),
      proposals: st?.proposals ?? [],
      proposalFor: (kind: string, targetId: number) => st?.proposals.find((p) => p.kind === kind && p.target_id === targetId),
      suggestions: st?.suggestions ?? [],
      present: st?.present ?? [],
    };
  }, [q.data]);
}
export type Collab = ReturnType<typeof useCollab>;

export function initials(name: string) {
  return name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((x) => x[0]?.toUpperCase()).join("") || "?";
}

export function Avatar({ person, size = 24, ring }: { person?: (CollabMember & { color: string }) | { name: string; color: string }; size?: number; ring?: boolean }) {
  if (!person) return null;
  return (
    <span title={person.name} aria-label={person.name}
      className={`inline-flex flex-none items-center justify-center rounded-full font-bold text-white ${ring ? "ring-2 ring-ground" : ""}`}
      style={{ width: size, height: size, fontSize: Math.max(9, Math.round(size * 0.4)), background: person.color }}>
      {initials(person.name)}
    </span>
  );
}

/** "Priya" for others, "you" for me. */
export function who(c: Collab, id: number | null | undefined) {
  if (!id) return "someone";
  return id === c.me ? "you" : (c.person(id)?.name.split(" ")[0] ?? "someone");
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>, sid: number) {
  for (const k of ["collab", "papers", "gaps", "writing", "session", "whatsnew", "analysis", "notices", "history"]) qc.invalidateQueries({ queryKey: [k, sid] });
  qc.invalidateQueries({ queryKey: ["sessions"] });
}

/** A pending proposal on a paper, gap or section, with Approve / Keep it / Withdraw. */
export function ProposalBanner({ sid, p, collab, canEdit, what }: { sid: number; p: Proposal; collab: Collab; canEdit: boolean; what: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const decide = useMutation({
    mutationFn: (d: "approve" | "reject" | "withdraw") => api.decide(sid, p.id, d),
    onSuccess: (r) => {
      invalidateAll(qc, sid);
      toast(r.status === "approved" ? "Approved" : r.status === "withdrawn" ? "Proposal withdrawn" : "Kept as it was");
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const mine = p.proposed_by === collab.me;
  const verb = { remove_paper: "removing", restore_paper: "restoring", untrack_gap: "untracking", delete_gap: "deleting", delete_section: "deleting" }[p.kind];
  const reason = p.payload?.reason ? p.payload.reason.replace(/_/g, " ") : null;
  const person = collab.person(p.proposed_by);
  return (
    <div className="flex flex-col gap-2 rounded-[10px] border border-[#F5C9A8] bg-[#FFF7F1] px-3 py-2.5" role="status">
      <div className="flex items-start gap-2.5 text-sm">
        <Avatar person={person} size={24} />
        <div className="min-w-0 flex-1">
          <b>{mine ? "You" : person?.name ?? p.proposed_by_name}</b> proposed {verb} {what}
          {(reason || p.reason_text) && <span className="block text-ink-2">“{p.reason_text || reason}”</span>}
          <span className="block text-xs text-ink-muted">Nothing changes until {mine ? "someone else" : "one of you"} approves.</span>
        </div>
      </div>
      {canEdit && (
        <div className="flex flex-wrap gap-1.5">
          {mine
            ? <button className="btn btn-sm" onClick={() => decide.mutate("withdraw")} disabled={decide.isPending}>{decide.isPending && <Spinner />}Withdraw</button>
            : <>
                <button className="btn btn-sm btn-primary" onClick={() => decide.mutate("approve")} disabled={decide.isPending}>{decide.isPending && <Spinner />}Approve</button>
                <button className="btn btn-sm" onClick={() => decide.mutate("reject")} disabled={decide.isPending}>Keep it</button>
              </>}
        </div>
      )}
    </div>
  );
}

/** All comment threads in the session, fetched once and filtered per item. */
export function useComments(sid: number) {
  return useQuery({ queryKey: ["comments", sid], queryFn: () => api.comments(sid), refetchInterval: 30_000 });
}

export function CommentThreads({ sid, collab, threads, target, quote, canComment, onDone }: {
  sid: number; collab: Collab; threads: CommentThread[]; target: { type: string; id: number };
  quote?: string | null; canComment: boolean; onDone?: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [body, setBody] = useState("");
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [reply, setReply] = useState("");
  const [showResolved, setShowResolved] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["comments", sid] }); qc.invalidateQueries({ queryKey: ["whatsnew", sid] }); };
  const add = useMutation({
    mutationFn: (b: { body: string; parent_id?: number }) => api.addComment(sid, b.parent_id ? b : { ...b, target_type: target.type, target_id: target.id, quote: quote ?? undefined }),
    onSuccess: () => { refresh(); setBody(""); setReply(""); setReplyTo(null); onDone?.(); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  const resolve = (id: number, resolved: boolean) => api.resolveComment(sid, id, resolved).then(refresh).catch((e) => toast(e.message, "error"));
  const open = threads.filter((t) => !t.resolved);
  const done = threads.filter((t) => t.resolved);
  const mentionHint = collab.members.filter((m) => m.id !== collab.me).map((m) => `@${m.name.split(" ")[0]}`).join(", ");

  function submit(e: FormEvent) { e.preventDefault(); if (body.trim()) add.mutate({ body }); }
  const Item = ({ c, small }: { c: { user_id: number; user_name: string; body: string; created_at: string }; small?: boolean }) => (
    <div className="flex gap-2">
      <Avatar person={collab.person(c.user_id) ?? { name: c.user_name, color: "#4B5563" }} size={small ? 20 : 24} />
      <div className="min-w-0 text-[13px]"><b>{c.user_id === collab.me ? "You" : c.user_name}</b> <span className="text-ink-muted">· {ago(c.created_at)}</span>
        <div className="whitespace-pre-wrap break-words text-ink">{c.body}</div></div>
    </div>
  );

  return (
    <div className="flex flex-col gap-2.5">
      {[...open, ...(showResolved ? done : [])].map((t) => (
        <div key={t.id} className={`flex flex-col gap-2 rounded-[10px] border p-3 ${t.resolved ? "border-line bg-ground opacity-80" : "border-[#F3D3A6] bg-white"}`}>
          {t.quote && <div className="border-l-[3px] border-amber pl-2 font-serif text-xs italic text-ink-muted">“{t.quote}”</div>}
          <Item c={t} />
          {t.replies.map((r) => <div key={r.id} className="pl-3"><Item c={r} small /></div>)}
          {canComment && (replyTo === t.id ? (
            <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); if (reply.trim()) add.mutate({ body: reply, parent_id: t.id }); }}>
              <label className="sr-only" htmlFor={`reply-${t.id}`}>Reply</label>
              <input id={`reply-${t.id}`} className="input h-9 text-[13px]" autoFocus value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Reply" />
              <button className="btn btn-sm" disabled={add.isPending || !reply.trim()}>Send</button>
            </form>
          ) : (
            <div className="flex gap-1.5">
              <button className="btn btn-sm btn-ghost h-8" onClick={() => setReplyTo(t.id)}>Reply</button>
              <button className="btn btn-sm btn-ghost h-8" onClick={() => resolve(t.id, !t.resolved)}>{t.resolved ? "Reopen" : "Resolve"}</button>
            </div>
          ))}
        </div>
      ))}
      {done.length > 0 && <button className="self-start text-xs font-semibold text-ink-muted hover:text-ink" onClick={() => setShowResolved(!showResolved)}>{showResolved ? "Hide" : "Show"} {done.length} resolved</button>}
      {canComment && (
        <form className="flex flex-col gap-1.5" onSubmit={submit}>
          {quote && <div className="border-l-[3px] border-amber pl-2 font-serif text-xs italic text-ink-muted">On: “{quote}”</div>}
          <label className="sr-only" htmlFor={`c-${target.type}-${target.id}`}>Comment</label>
          <textarea id={`c-${target.type}-${target.id}`} className="textarea min-h-[64px] text-[13px]" value={body} onChange={(e) => setBody(e.target.value)}
            placeholder={mentionHint ? `Comment, or mention ${mentionHint}` : "Comment"} />
          <button className="btn btn-sm self-start" disabled={add.isPending || !body.trim()}>{add.isPending && <Spinner />}Comment</button>
        </form>
      )}
    </div>
  );
}

/** Small "💬 2" button that opens the threads for one item in a modal. */
export function CommentsButton({ sid, collab, threads, target, title, canComment }: {
  sid: number; collab: Collab; threads: CommentThread[]; target: { type: string; id: number }; title: string; canComment: boolean;
}) {
  const [open, setOpen] = useState(false);
  const mine = threads.filter((t) => t.target_type === target.type && t.target_id === target.id);
  const unresolved = mine.filter((t) => !t.resolved).length;
  if (!canComment && !mine.length) return null;
  return (
    <>
      <button className={`btn btn-sm ${unresolved ? "border-[#F3D3A6] text-amber-ink" : ""}`} onClick={() => setOpen(true)}
        aria-label={`Comments${unresolved ? `, ${unresolved} open` : ""}`}>
        <MessageCircle size={15} aria-hidden="true" />{unresolved || ""}
      </button>
      {open && (
        <Modal title={`Comments · ${title}`} onClose={() => setOpen(false)}>
          <CommentThreads sid={sid} collab={collab} threads={mine} target={target} canComment={canComment} />
        </Modal>
      )}
    </>
  );
}

export function HistoryButton({ sid, target, title }: { sid: number; target: { type: string; id: number }; title: string }) {
  const [open, setOpen] = useState(false);
  const h = useQuery({ queryKey: ["history", sid, target.type, target.id], queryFn: () => api.history(sid, target.type, target.id), enabled: open });
  return (
    <>
      <button className="text-xs font-semibold text-ink-muted hover:text-ink" onClick={() => setOpen(true)}>History</button>
      {open && (
        <Modal title={`History · ${title}`} onClose={() => setOpen(false)}>
          {h.isLoading ? <div className="flex items-center gap-2 text-sm text-ink-muted"><Spinner />Loading…</div>
            : !h.data?.length ? <p className="text-sm text-ink-muted">No changes recorded yet.</p>
            : <ol className="flex flex-col gap-2.5">{h.data.map((a) => (
                <li key={a.id} className="flex gap-2.5 text-sm">
                  <Clock size={15} className="mt-0.5 flex-none text-ink-muted" aria-hidden="true" />
                  <span><b>{a.user_name ?? "Someone"}</b> {a.summary}<span className="block text-xs text-ink-muted">{new Date(a.at).toLocaleString()}</span></span>
                </li>))}
              </ol>}
          <p className="mt-3 text-xs text-ink-muted">Every change is recorded with who made it and when. History can't be edited.</p>
        </Modal>
      )}
    </>
  );
}

export function ago(iso: string | null | undefined) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 172800) return "yesterday";
  return new Date(iso).toLocaleDateString();
}

/** Where an activity row or "needs you" item should take the user. */
function linkFor(sid: number, t?: { target_type?: string | null; target_id?: number | null; kind?: string; section_id?: number }) {
  if (!t) return `/s/${sid}`;
  if (t.section_id) return `/s/${sid}/write?section=${t.section_id}`;
  const type = t.target_type ?? (t.kind?.includes("paper") ? "paper" : t.kind?.includes("gap") ? "gap" : t.kind?.includes("section") ? "section" : undefined);
  if (type === "paper") return `/s/${sid}/papers`;
  if (type === "gap" && t.target_id) return `/s/${sid}/explore/gaps/${t.target_id}`;
  if (type === "section" && t.target_id) return `/s/${sid}/write?section=${t.target_id}`;
  if (type === "theme") return `/s/${sid}/explore/themes`;
  return `/s/${sid}/papers`;
}

export function WhatsNewPanel({ sid, collab, data, onClose }: { sid: number; collab: Collab; data: WhatsNew | undefined; onClose: () => void }) {
  return (
    <aside aria-label="What's new" className="flex h-full flex-col bg-white">
      <div className="flex flex-none items-center justify-between gap-3 border-b border-line px-[18px] py-3.5">
        <span><span className="block text-[15px] font-bold">What's new</span>
          <span className="block text-xs text-ink-muted">{data?.last_seen_at ? `Since you were last here · ${ago(data.last_seen_at)}` : "Everything so far"}</span></span>
        <button className="btn btn-sm btn-ghost" onClick={onClose} aria-label="Close what's new"><X size={16} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!data ? <div className="flex items-center gap-2 p-5 text-sm text-ink-muted"><Spinner />Loading…</div> : <>
          <div className="px-[18px] pb-1.5 pt-3.5"><span className="sub">Needs you</span></div>
          {data.needs_you.length === 0 && <div className="px-[18px] pb-2 text-[13px] text-ink-muted">Nothing waiting for you.</div>}
          {data.needs_you.map((n) => (
            <Link key={`${n.type}-${n.id}`} to={linkFor(sid, n)} onClick={onClose}
              className="flex gap-2.5 border-b border-[#F1F3F5] px-[18px] py-3 text-ink no-underline hover:bg-ground">
              <Avatar person={collab.members.find((m) => m.name === n.user_name) ?? { name: n.user_name, color: "#4B5563" }} size={28} />
              <span className="text-sm"><b>{n.user_name}</b> {n.text}
                <span className="block text-xs font-semibold text-[#9A3412]">{n.type === "proposal" ? "Waiting for your decision" : n.type === "suggestion" ? "Your section · accept or reject" : "Reply or resolve"}</span></span>
            </Link>
          ))}
          <div className="px-[18px] pb-1.5 pt-4"><span className="sub">Other changes</span></div>
          {data.changes.length === 0 && <div className="px-[18px] text-[13px] text-ink-muted">Nobody else has changed anything yet.</div>}
          {data.changes.map((a) => {
            const fresh = !data.last_seen_at || new Date(a.at) > new Date(data.last_seen_at);
            return (
              <Link key={a.id} to={linkFor(sid, a)} onClick={onClose}
                className="flex gap-2.5 border-b border-[#F1F3F5] px-[18px] py-3 text-ink no-underline hover:bg-ground">
                <Avatar person={collab.person(a.user_id) ?? { name: a.user_name ?? "?", color: "#4B5563" }} size={28} />
                <span className="min-w-0 text-sm"><b>{a.user_name ?? "Someone"}</b> {a.summary}
                  <span className="block text-xs text-ink-muted">{ago(a.at)}{fresh && <span className="ml-1.5 font-semibold text-teal">· new</span>}</span></span>
              </Link>
            );
          })}
        </>}
      </div>
      <div className="flex-none border-t border-line px-[18px] py-3 text-xs text-ink-muted">
        <CheckCircle2 size={13} className="mr-1 inline text-teal" aria-hidden="true" />Every change is recorded and can be undone. Removed papers can always be restored.
      </div>
    </aside>
  );
}
