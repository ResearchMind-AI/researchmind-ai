import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, NotebookPen, X } from "lucide-react";
import { api } from "../api";
import type { ChatMessage, Gap, Notice, Paper, PartnerContext } from "../types";
import ChatThread, { type HandedQuestion } from "./ChatThread";
import { CitedText, Logo, useToast } from "./ui";

interface Props {
  sid: number;
  ctx: PartnerContext;
  handed: HandedQuestion | null;
  paperMap: Map<number, Paper>;
  canAsk: boolean;
  onClearContext: () => void;
  onClose: () => void;
  onAsk: (ctx: PartnerContext, q: string) => void;
}

const dismissKey = (sid: number) => `rm.notices.${sid}`;
function loadDismissed(sid: number): string[] {
  try { return JSON.parse(localStorage.getItem(dismissKey(sid)) || "[]"); } catch { return []; }
}

const SUGGESTIONS: Record<PartnerContext["kind"], string[]> = {
  session: ["Where do the findings disagree?", "What are the main methods used?", "Which populations are under-studied?"],
  gap: ["How could I design a study to address this?", "What would make this gap hard to study?", "Which of my papers come closest to it?"],
  theme: ["What are the strongest findings here?", "Where do these studies disagree?", "How does this theme connect to the others?"],
  section: ["Is my draft well supported by the evidence?", "What am I missing in this section?", "How should I structure this section?"],
};

function chipLabel(ctx: PartnerContext): string {
  switch (ctx.kind) {
    case "gap": return `Your gap: ${ctx.title}`;
    case "theme": return `Theme: ${ctx.label}`;
    case "section": return `Section: ${ctx.heading}`;
    default: return "The whole session";
  }
}

export default function PartnerPanel({ sid, ctx, handed, paperMap, canAsk, onClearContext, onClose, onAsk }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const notices = useQuery({ queryKey: ["notices", sid], queryFn: () => api.notices(sid), staleTime: 15_000 });
  const [dismissed, setDismissed] = useState<string[]>(() => loadDismissed(sid));
  const notice: Notice | undefined = useMemo(() => (notices.data ?? []).find((n) => !dismissed.includes(n.id)), [notices.data, dismissed]);

  function dismiss(id: string) {
    const next = [...dismissed, id];
    setDismissed(next);
    try { localStorage.setItem(dismissKey(sid), JSON.stringify(next.slice(-200))); } catch { /* private mode */ }
  }

  async function addToGapNotes(m: ChatMessage) {
    if (ctx.kind !== "gap") return;
    const gaps = qc.getQueryData<Gap[]>(["gaps", sid]);
    const current = gaps?.find((g) => g.id === ctx.id)?.notes ?? "";
    try {
      await api.updateGap(sid, ctx.id, { notes: [current, m.content.trim()].filter(Boolean).join("\n\n") });
      qc.invalidateQueries({ queryKey: ["gaps", sid] });
      qc.invalidateQueries({ queryKey: ["writing", sid] });
      toast("Added to your gap notes");
    } catch (e) { toast((e as Error).message, "error"); }
  }
  async function copy(m: ChatMessage) {
    try { await navigator.clipboard.writeText(m.content); toast("Copied"); } catch { toast("Couldn't copy here", "error"); }
  }

  const answerActions = (m: ChatMessage) => (
    <div className="flex flex-wrap gap-1.5">
      {ctx.kind === "gap" && canAsk && <button className="btn btn-sm" onClick={() => addToGapNotes(m)}><NotebookPen size={14} aria-hidden="true" />Add to my gap notes</button>}
      <button className="btn btn-sm btn-ghost" onClick={() => copy(m)}><Copy size={14} aria-hidden="true" />Copy</button>
    </div>
  );

  const threadKey = `${ctx.kind}-${"id" in ctx ? ctx.id : "index" in ctx ? ctx.index : 0}`;
  return (
    <aside aria-label="Research partner" className="flex h-full flex-col bg-white">
      <div className="flex flex-none items-center justify-between gap-3 border-b border-line px-[18px] py-3.5">
        <span className="flex items-center gap-2.5">
          <Logo size={30} />
          <span><span className="block text-[15px] font-bold">Research partner</span><span className="block text-xs text-ink-muted">Knows your papers, gaps and notes</span></span>
        </span>
        <button className="btn btn-sm btn-ghost" onClick={onClose} aria-label="Close research partner"><X size={16} /></button>
      </div>
      <div className="flex flex-none flex-wrap items-center gap-1.5 border-b border-line px-[18px] py-2.5">
        <span className="text-xs font-semibold text-ink-muted">About</span>
        <span className={`chip max-w-full ${ctx.kind === "session" ? "" : "chip-teal"}`}>
          <span className="truncate">{chipLabel(ctx)}</span>
          {ctx.kind !== "session" && <button className="ml-0.5 font-bold" onClick={onClearContext} aria-label="Ask about the whole session instead">×</button>}
        </span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-4 px-[18px] py-4">
        {notice && canAsk && (
          <div className="flex flex-none flex-col gap-2 rounded-xl border border-teal-line bg-teal-wash px-3.5 py-3">
            <span className="text-xs font-bold text-teal-ink">I noticed</span>
            <p className="text-sm text-ink"><CitedText text={notice.text} papers={paperMap} /></p>
            <div className="flex flex-wrap gap-1.5">
              {notice.actions.map((a) => (
                <button key={a.label} className="btn btn-sm" onClick={() => {
                  if (a.ask && a.gap_id) {
                    const g = qc.getQueryData<Gap[]>(["gaps", sid])?.find((x) => x.id === a.gap_id);
                    onAsk({ kind: "gap", id: a.gap_id, title: g?.title ?? "this gap" }, a.ask);
                  } else if (a.to) navigate(`/s/${sid}/${a.to}`);
                  dismiss(notice.id);
                }}>{a.label}</button>
              ))}
              <button className="btn btn-sm btn-ghost" onClick={() => dismiss(notice.id)}>Not now</button>
            </div>
          </div>
        )}
        <ChatThread key={threadKey} sid={sid} paperMap={paperMap} canAsk={canAsk} fill
          gapId={ctx.kind === "gap" ? ctx.id : undefined}
          focus={ctx.kind === "theme" ? { theme: ctx.index } : ctx.kind === "section" ? { section_id: ctx.id } : undefined}
          suggestions={SUGGESTIONS[ctx.kind]} initial={handed} actions={answerActions}
          placeholder={ctx.kind === "gap" ? "Ask about this gap" : ctx.kind === "theme" ? "Ask about this theme" : ctx.kind === "section" ? "Ask about this section" : "Ask anything about your papers"} />
      </div>
    </aside>
  );
}
