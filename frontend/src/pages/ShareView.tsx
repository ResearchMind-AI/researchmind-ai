import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus, X } from "lucide-react";
import { api } from "../api";
import { Empty, ErrorNote, PageLoading, Spinner, useToast } from "../components/ui";
import { useSession } from "./SessionLayout";

const ROLES = [
  { value: "viewer", label: "Viewer", text: "Can read papers, themes, gaps and writing." },
  { value: "contributor", label: "Contributor", text: "Can also find papers, ask questions, manage gaps and write." },
];

export default function ShareView() {
  const { sid, session } = useSession();
  const qc = useQueryClient();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const members = useQuery({ queryKey: ["members", sid], queryFn: () => api.members(sid), enabled: session.can_manage });
  const share = useMutation({
    mutationFn: () => api.share(sid, email.trim().toLowerCase(), role),
    onSuccess: () => { toast(`Shared with ${email.trim()}`); setEmail(""); qc.invalidateQueries({ queryKey: ["members", sid] }); },
    onError: (e: Error) => toast(e.message, "error"),
  });
  async function remove(userId: number, who: string) {
    if (!window.confirm(`Remove ${who} from this session?`)) return;
    try { await api.removeMember(sid, userId); qc.invalidateQueries({ queryKey: ["members", sid] }); }
    catch (e) { toast((e as Error).message, "error"); }
  }

  if (!session.can_manage) return <Empty title="Only the session owner can share it" />;
  if (members.isLoading) return <PageLoading />;
  if (members.error) return <ErrorNote error={members.error} />;

  function submit(e: FormEvent) { e.preventDefault(); share.mutate(); }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[1fr_1fr]">
      <form className="card flex flex-col gap-4 p-6" onSubmit={submit}>
        <div><h2 className="h-serif text-[22px]">Invite someone</h2><p className="text-sm text-ink-muted">They need a ResearchMind account with this email first.</p></div>
        <div><label className="label" htmlFor="share-email">Email</label>
          <input id="share-email" type="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="colleague@university.edu" /></div>
        <fieldset className="flex flex-col gap-2">
          <legend className="label">Access</legend>
          {ROLES.map((r) => (
            <label key={r.value} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 ${role === r.value ? "border-teal bg-teal-wash" : "border-line"}`}>
              <input type="radio" name="role" className="mt-1 accent-teal" value={r.value} checked={role === r.value} onChange={() => setRole(r.value)} />
              <span><span className="font-semibold">{r.label}</span><span className="block text-[13px] text-ink-muted">{r.text}</span></span>
            </label>
          ))}
        </fieldset>
        <button className="btn btn-primary self-start" disabled={share.isPending || !email.trim()}>{share.isPending ? <Spinner /> : <UserPlus size={16} aria-hidden="true" />}Share session</button>
      </form>
      <section className="card flex flex-col gap-3 p-6">
        <h2 className="h-serif text-[22px]">People with access</h2>
        <ul className="flex flex-col divide-y divide-line">
          {(members.data ?? []).map((m) => (
            <li key={m.user_id} className="flex items-center gap-3 py-3">
              <div className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-chip text-[13px] font-bold">{(m.full_name || m.email)[0]?.toUpperCase()}</div>
              <div className="min-w-0 flex-1"><div className="truncate font-semibold">{m.full_name || m.email}</div>{m.full_name && <div className="truncate text-[13px] text-ink-muted">{m.email}</div>}</div>
              <span className={`chip ${m.role === "owner" ? "chip-teal" : ""}`}>{m.role}</span>
              {m.role !== "owner" && <button className="btn btn-sm btn-ghost" onClick={() => remove(m.user_id, m.email)} aria-label={`Remove ${m.email}`}><X size={14} /></button>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
