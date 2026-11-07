import { Link, useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Layers, MessageSquare, PenLine, Plus, Target } from "lucide-react";
import { api } from "../api";

const STEPS = [
  { icon: BookOpen, title: "Find papers", text: "Searches OpenAlex, Semantic Scholar, PubMed and arXiv and ranks results by relevance." },
  { icon: Layers, title: "Map the themes", text: "Groups the papers into themes with key findings and frequent authors." },
  { icon: Target, title: "Spot the gaps", text: "Suggests under-explored areas, and checks your own gap ideas against recent work." },
  { icon: MessageSquare, title: "Ask questions", text: "Answers drawn only from your papers, with numbered citations." },
  { icon: PenLine, title: "Write your review", text: "A section-by-section guide and feedback on your draft. You stay the author." },
];

export default function HomePage() {
  const { openNew } = useOutletContext<{ openNew: () => void }>();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <div className="text-[13px] text-ink-muted">Welcome</div>
        <h1 className="h-serif text-[34px] leading-tight">Start a research session</h1>
        <p className="max-w-2xl text-[15px] text-ink-muted">Describe your topic and ResearchMind builds an evidence base you can explore, question and write from.</p>
        <div className="mt-2"><button className="btn btn-primary" onClick={openNew}><Plus size={16} aria-hidden="true" />New research session</button></div>
      </header>
      <section className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3.5" aria-label="How it works">
        {STEPS.map(({ icon: Icon, title, text }, i) => (
          <div key={title} className="card flex flex-col gap-2.5 p-5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-teal-soft text-teal-ink"><Icon size={18} aria-hidden="true" /></div>
              <span className="text-xs font-bold text-ink-muted">STEP {i + 1}</span>
            </div>
            <div className="font-semibold">{title}</div>
            <div className="text-[13px] text-ink-muted">{text}</div>
          </div>
        ))}
      </section>
      {!!sessions.data?.length && (
        <section className="flex flex-col gap-3">
          <div className="sub">Recent sessions</div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-3.5">
            {sessions.data.slice(0, 6).map((s) => (
              <Link key={s.id} to={`/s/${s.id}`} className="card flex flex-col gap-2 p-5 text-ink no-underline hover:border-teal-line">
                <span className="h-serif text-lg leading-snug">{s.title}</span>
                <span className="flex flex-wrap gap-1.5"><span className="chip">{s.paper_count} papers</span><span className="chip">{s.theme_count} themes</span><span className="chip">{s.gap_count} gaps</span>{s.role !== "owner" && <span className="chip chip-blue">{s.role}</span>}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
