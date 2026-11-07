import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Square } from "lucide-react";
import { api, chatUrl, streamSSE, type ChatEvent } from "../api";
import type { ChatMessage, Paper } from "../types";
import { CitedText, Spinner } from "./ui";

interface Props {
  sid: number;
  gapId?: number;
  paperMap: Map<number, Paper>;
  canAsk: boolean;
  suggestions?: string[];
  placeholder?: string;
  compact?: boolean;
  initialQuestion?: string;
}

function Bubble({ m, paperMap }: { m: ChatMessage; paperMap: Map<number, Paper> }) {
  if (m.role === "user") {
    return <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-navy px-4 py-2.5 text-[15px] text-white">{m.content}</div>;
  }
  return (
    <div className="flex max-w-full flex-col gap-2">
      <div className="text-[15px] leading-relaxed text-ink"><CitedText text={m.content || "…"} papers={paperMap} markdown /></div>
      {!!m.citations?.length && (
        <details className="text-[13px] text-ink-muted">
          <summary className="cursor-pointer select-none font-semibold text-teal">Sources ({m.citations.length})</summary>
          <ol className="mt-1.5 flex flex-col gap-1">
            {m.citations.map((c) => (
              <li key={c.n} className="flex gap-2"><span className="ref flex-none">{c.n}</span>
                {c.url ? <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> : c.title}{c.year ? ` (${c.year})` : ""}</li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

export default function ChatThread({ sid, gapId, paperMap, canAsk, suggestions = [], placeholder, compact, initialQuestion }: Props) {
  const qc = useQueryClient();
  const key = ["messages", sid, gapId ?? 0];
  const history = useQuery({ queryKey: key, queryFn: () => api.messages(sid, gapId) });
  const [pending, setPending] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const messages = [...(history.data ?? []), ...pending];
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [messages.length, pending]);
  useEffect(() => () => abort.current?.abort(), []);

  async function ask(question: string) {
    const q = question.trim();
    if (q.length < 2 || busy) return;
    setText(""); setError(null); setBusy(true);
    const now = new Date().toISOString();
    setPending([{ role: "user", content: q, citations: null, created_at: now }, { role: "assistant", content: "", citations: null, created_at: now }]);
    abort.current = new AbortController();
    const patch = (fn: (a: ChatMessage) => ChatMessage) => setPending((p) => [p[0], fn(p[1])]);
    try {
      await streamSSE<ChatEvent>(chatUrl(sid), { question: q, gap_id: gapId }, (e) => {
        if (e.type === "token") patch((a) => ({ ...a, content: a.content + e.text }));
        else if (e.type === "done") patch((a) => ({ ...a, content: e.answer, citations: e.citations }));
        else if (e.type === "error") setError(e.message);
      }, abort.current.signal);
      await qc.invalidateQueries({ queryKey: key });
      setPending([]);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
      else { await qc.invalidateQueries({ queryKey: key }); setPending([]); }
    } finally { setBusy(false); }
  }

  // A question handed over from elsewhere (e.g. "Ask about this theme") is asked once history has loaded.
  const asked = useRef(false);
  useEffect(() => {
    if (initialQuestion && canAsk && !history.isLoading && !asked.current) { asked.current = true; ask(initialQuestion); }
  }); // eslint-disable-line react-hooks/exhaustive-deps

  function submit(e: FormEvent) { e.preventDefault(); ask(text); }

  return (
    <div className="flex flex-col gap-4">
      <div className={`flex flex-col gap-5 ${compact ? "max-h-[460px] overflow-y-auto pr-1" : ""}`} aria-live="polite">
        {history.isLoading && <div className="flex items-center gap-2 text-sm text-ink-muted"><Spinner />Loading conversation…</div>}
        {!history.isLoading && messages.length === 0 && suggestions.length > 0 && canAsk && (
          <div className="flex flex-col gap-2">
            <div className="sub">Try asking</div>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => <button key={s} className="btn btn-sm h-auto py-1.5 text-left font-normal" onClick={() => ask(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {messages.map((m, i) => <Bubble key={i} m={m} paperMap={paperMap} />)}
        {busy && pending[1]?.content === "" && <div className="flex items-center gap-2 text-sm text-ink-muted"><Spinner />Reading your papers…</div>}
        {error && <div className="rounded-[10px] bg-[#FBEFEE] px-3 py-2 text-sm text-[#7F1D1D]" role="alert">{error}</div>}
        <div ref={end} />
      </div>
      {canAsk ? (
        <form onSubmit={submit} className="flex items-end gap-2 rounded-card border border-line bg-white p-2 focus-within:border-teal">
          <label className="sr-only" htmlFor={`ask-${gapId ?? 0}`}>Your question</label>
          <textarea id={`ask-${gapId ?? 0}`} rows={compact ? 2 : 2} value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(text); } }}
            placeholder={placeholder ?? "Ask a question about your papers"} className="min-h-[44px] flex-1 resize-none border-0 bg-transparent px-2 py-1.5 text-[15px] outline-none" />
          {busy
            ? <button type="button" className="btn btn-sm h-9 w-9 p-0" onClick={() => abort.current?.abort()} aria-label="Stop"><Square size={14} /></button>
            : <button type="submit" className="btn btn-primary h-9 w-9 p-0" disabled={text.trim().length < 2} aria-label="Send"><ArrowUp size={18} /></button>}
        </form>
      ) : <div className="text-[13px] text-ink-muted">You have view-only access to this session.</div>}
      <div className="text-xs text-ink-muted">Answers use only the abstracts of this session's papers. Check the full text before citing.</div>
    </div>
  );
}
