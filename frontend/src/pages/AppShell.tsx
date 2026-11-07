import { useState, type FormEvent } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Menu, Plus, X } from "lucide-react";
import { api } from "../api";
import type { User } from "../types";
import { Logo, Modal, Spinner, useToast } from "../components/ui";

export function NewSessionModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [topic, setTopic] = useState("");
  const [title, setTitle] = useState("");
  const create = useMutation({
    mutationFn: () => api.createSession(topic.trim(), title.trim() || undefined),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      onClose();
      navigate(`/s/${s.id}/papers`, { state: { run: true } });
    },
    onError: (e: Error) => toast(e.message, "error"),
  });
  function submit(e: FormEvent) { e.preventDefault(); if (topic.trim().length >= 5) create.mutate(); }
  return (
    <Modal title="New research session" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div>
          <label className="label" htmlFor="topic">What are you researching?</label>
          <textarea id="topic" className="textarea min-h-[110px] text-[15px]" required minLength={5} value={topic} onChange={(e) => setTopic(e.target.value)}
                    placeholder="e.g. Large language models for clinical decision support in emergency medicine" autoFocus />
        </div>
        <div><label className="label" htmlFor="title">Short title <span className="font-normal text-ink-muted">(optional)</span></label>
          <input id="title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} /></div>
        <p className="text-[13px] text-ink-muted">ResearchMind will search OpenAlex, Semantic Scholar, PubMed and arXiv, then group the papers into themes and suggest gaps. It takes about a minute.</p>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending || topic.trim().length < 5}>
            {create.isPending && <Spinner />}Create and find papers
          </button>
        </div>
      </form>
    </Modal>
  );
}

function initials(u: User) {
  const name = u.full_name || u.email;
  return name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((x) => x[0]?.toUpperCase()).join("");
}

export default function AppShell({ user }: { user: User }) {
  const [creating, setCreating] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources, staleTime: Infinity });

  async function logout() {
    try { await api.logout(); } finally {
      // Full reload so no cached data from this account survives.
      window.location.assign("/");
    }
  }

  const mine = (sessions.data ?? []).filter((s) => s.role === "owner");
  const shared = (sessions.data ?? []).filter((s) => s.role !== "owner");
  const SessLink = ({ s }: { s: (typeof mine)[number] }) => (
    <NavLink to={`/s/${s.id}`} onClick={() => setMenuOpen(false)}
      className={({ isActive }) => `flex flex-col gap-0.5 rounded-[10px] px-3 py-2.5 no-underline ${isActive ? "bg-navy-2 text-white" : "text-navy-text hover:bg-white/5 hover:text-white"}`}>
      <span className="line-clamp-2 font-semibold leading-snug">{s.title}</span>
      <span className="text-xs text-navy-soft">{s.paper_count} papers{s.role !== "owner" ? ` · ${s.role}` : ""}</span>
    </NavLink>
  );

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <header className="flex items-center justify-between bg-navy px-4 py-3 text-white md:hidden">
        <div className="flex items-center gap-2.5 font-bold"><Logo size={28} /> ResearchMind</div>
        <button className="btn btn-sm border-navy-line bg-transparent text-white hover:bg-navy-2" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen} aria-label="Menu">
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      </header>

      <div className="bg-navy md:w-[272px] md:flex-none">
      <aside className={`${menuOpen ? "flex" : "hidden"} w-full flex-col gap-5 px-3.5 py-5 text-navy-text md:sticky md:top-0 md:flex md:h-screen md:overflow-y-auto`}>
        <div className="hidden items-center gap-2.5 px-1.5 text-base font-bold text-white md:flex"><Logo /> ResearchMind</div>
        <button className="btn w-full border-navy-line bg-transparent text-[#E6EDF3] hover:bg-navy-2" onClick={() => setCreating(true)}>
          <Plus size={16} aria-hidden="true" /> New research session
        </button>
        <nav className="flex flex-col gap-1.5" aria-label="Sessions">
          <div className="px-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-navy-muted">Your sessions</div>
          {sessions.isLoading && <div className="px-3 py-1 text-sm text-navy-muted">Loading…</div>}
          {!sessions.isLoading && mine.length === 0 && <div className="px-3 py-1 text-[13px] text-navy-muted">No sessions yet</div>}
          {mine.map((s) => <SessLink key={s.id} s={s} />)}
          <div className="mt-2.5 px-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-navy-muted">Shared with you</div>
          {shared.length === 0 && <div className="px-3 py-1 text-[13px] text-navy-muted">Nothing shared yet</div>}
          {shared.map((s) => <SessLink key={s.id} s={s} />)}
        </nav>
        <div className="mt-auto flex flex-col gap-3.5">
          <div className="flex flex-col gap-0.5">
            <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-navy-muted">Paper sources</div>
            {(sources.data ?? []).map((s) => (
              <div key={s.name} className="flex items-center justify-between px-2 py-0.5 text-[13px]" title={s.detail}>
                <span className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${s.mode === "full" ? "bg-teal-bright" : "bg-amber-dot"}`} aria-hidden="true" />{s.label}</span>
                <span className="text-navy-muted">{s.mode}</span>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2.5 border-t border-navy-line px-2 pt-3">
            <div className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-full bg-navy-3 text-[13px] font-bold text-white">{initials(user)}</div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold text-white">{user.full_name || user.email}</div>
              <button className="text-xs text-navy-soft hover:text-white" onClick={logout}>Log out</button>
            </div>
          </div>
        </div>
      </aside>
      </div>

      <main className="min-w-0 flex-1 px-4 pb-14 pt-6 transition-[padding] md:px-10 md:pt-7 xl:pr-[calc(2.5rem+var(--rm-partner,0px))]">
        <div className="mx-auto max-w-[1120px]">
          <Outlet context={{ openNew: () => setCreating(true) }} />
        </div>
      </main>
      {creating && <NewSessionModal onClose={() => setCreating(false)} />}
    </div>
  );
}
