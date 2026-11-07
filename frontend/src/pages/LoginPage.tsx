import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PenLine, Search, Target } from "lucide-react";
import { api } from "../api";
import { Logo, Spinner } from "../components/ui";

const FEATURES = [
  { icon: Search, title: "Search four free databases at once", text: "OpenAlex, Semantic Scholar, PubMed and arXiv, ranked by relevance." },
  { icon: Target, title: "Track and test research gaps", text: "Pin gaps, check if they are really open, and discuss each one." },
  { icon: PenLine, title: "Write with a guide, not a ghostwriter", text: "Section-by-section points, sources and feedback on your draft." },
];

export default function LoginPage() {
  const qc = useQueryClient();
  const config = useQuery({ queryKey: ["config"], queryFn: api.config });
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [form, setForm] = useState({ email: "", password: "", full_name: "", invite_code: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = mode === "login"
        ? await api.login(form.email, form.password)
        : await api.register({ email: form.email, password: form.password, full_name: form.full_name || undefined,
                               invite_code: form.invite_code || undefined });
      qc.setQueryData(["me"], user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-wrap">
      <section className="hidden flex-[1_1_520px] flex-col justify-between gap-12 bg-navy px-16 py-14 text-navy-text md:flex">
        <div className="flex items-center gap-3 text-lg font-bold text-white"><Logo size={34} /> ResearchMind</div>
        <div className="flex max-w-[520px] flex-col gap-7">
          <h1 className="h-serif text-[44px] leading-[1.15] text-white">From a research question to a literature review you write yourself.</h1>
          <p className="text-[17px] text-[#B8C5D2]">ResearchMind finds the papers, maps the themes and surfaces the gaps. You stay the author.</p>
          <div className="mt-2 flex flex-col gap-5">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <div key={title} className="flex items-start gap-3.5">
                <div className="flex h-9 w-9 flex-none items-center justify-center rounded-[10px] bg-white/[0.08] text-teal-bright"><Icon size={18} aria-hidden="true" /></div>
                <div><div className="font-semibold text-white">{title}</div><div className="text-[#B8C5D2]">{text}</div></div>
              </div>
            ))}
          </div>
        </div>
        <div className="text-[13px] text-[#8597A8]">Answers are based on paper abstracts. Always verify against the full text.</div>
      </section>

      <section className="flex flex-[1_1_440px] items-center justify-center px-6 py-12">
        <div className="flex w-full max-w-[420px] flex-col gap-6">
          <div className="flex items-center gap-3 text-lg font-bold md:hidden"><Logo size={30} /> ResearchMind</div>
          <div>
            <h2 className="h-serif text-[30px]">{mode === "login" ? "Welcome back" : "Create your account"}</h2>
            <p className="text-ink-muted">{mode === "login" ? "Log in to continue your research sessions." : "Start your first research session in minutes."}</p>
          </div>
          <div className="flex gap-1 rounded-xl bg-[#E9EDF1] p-1" role="tablist" aria-label="Account">
            {(["login", "signup"] as const).map((m) => (
              <button key={m} role="tab" aria-selected={mode === m} onClick={() => { setMode(m); setError(null); }}
                className={`h-10 flex-1 rounded-[9px] text-sm font-semibold ${mode === m ? "bg-white text-ink shadow-sm" : "text-ink-muted"}`}>
                {m === "login" ? "Log in" : "Create account"}
              </button>
            ))}
          </div>
          <form className="flex flex-col gap-4" onSubmit={submit}>
            {mode === "signup" && (
              <div><label className="label" htmlFor="name">Full name</label><input id="name" className="input" value={form.full_name} onChange={set("full_name")} autoComplete="name" /></div>
            )}
            <div><label className="label" htmlFor="email">Email</label><input id="email" type="email" required className="input" value={form.email} onChange={set("email")} autoComplete="email" /></div>
            <div>
              <label className="label" htmlFor="password">Password{mode === "signup" && <span className="font-normal text-ink-muted"> · 8+ characters</span>}</label>
              <input id="password" type="password" required minLength={mode === "signup" ? 8 : undefined} className="input" value={form.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} />
            </div>
            {mode === "signup" && config.data?.invite_required && (
              <div><label className="label" htmlFor="invite">Invite code</label><input id="invite" required className="input" value={form.invite_code} onChange={set("invite_code")} /></div>
            )}
            {error && <div className="rounded-[10px] bg-[#FBEFEE] px-3 py-2 text-sm text-[#7F1D1D]" role="alert">{error}</div>}
            <button type="submit" className="btn btn-primary h-[46px] text-[15px]" disabled={busy}>
              {busy && <Spinner />}{mode === "login" ? "Log in" : "Create account"}
            </button>
          </form>
          <p className="text-[13px] text-ink-muted">
            {mode === "login" ? "New here? Create an account with the invite code you were sent." : "Already have an account? Switch to Log in."} You stay logged in on this device for 7 days.
          </p>
        </div>
      </section>
    </div>
  );
}
