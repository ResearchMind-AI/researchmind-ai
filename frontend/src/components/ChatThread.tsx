import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Square } from "lucide-react";
import { api, chatUrl, streamSSE, type ChatEvent } from "../api";
import type { ChatMessage, Paper } from "../types";
import { CitedText, Spinner } from "./ui";

/** A question handed over from elsewhere ("Ask about this theme"); `nonce` makes repeats ask again. */
export interface HandedQuestion { q: string; nonce: number }

interface Props {
  sid: number;
  gapId?: number;
  /** Focus the answer on a theme (index) or a writing section; stays in the main thread. */
  focus?: { theme?: number; section_id?: number };
  paperMap: Map<number, Paper>;
  canAsk: boolean;
  suggestions?: string[];
  placeholder?: string;
  /** Fill the parent's height: messages scroll, the input stays at the bottom. */
  fill?: boolean;
  initial?: HandedQuestion | null;
  /** Buttons under an answer, e.g. "Add to my gap notes". */
  actions?: (m: ChatMessage) => ReactNode;
}

function Bubble({ m, paperMap, actions }: { m: ChatMessage; paperMap: Map<number, Paper>; actions?: ReactNode }) {
  if (m.role === "user") {
    return <div className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-navy px-4 py-2.5 text-[15px] text-white">{m.content}</div>;
  }
  return (
    <div className="flex max-w-full flex-col gap-2">
      <div className="text-[15px] leading-relaxed text-ink"><CitedText text={m.content || "…"} papers={paperMap} markdown /></div>
      {actions}
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

export default function ChatThread({ sid, gapId, focus, paperMap, canAsk, suggestions = [], placeholder, fill, initial, actions }: Props) {
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
      await streamSSE<ChatEvent>(chatUrl(sid), { question: q, gap_id: gapId, ...focus }, (e) => {
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

  // Ask a handed-over question once the history has loaded (and again for a new nonce).
  const lastNonce = useRef<number | null>(null);
  useEffect(() => {
    if (initial && canAsk && !history.isLoading && !busy && lastNonce.current !== initial.nonce) {
      lastNonce.current = initial.nonce;
      ask(initial.q);
    }
  }); // eslint-disable-line react-hooks/exhaustive-deps

  function submit(e: FormEvent) { e.preventDefault(); ask(text); }
  const inputId = `ask-${gapId ?? 0}-${focus?.theme ?? ""}-${focus?.section_id ?? ""}`;

  return (
    <div className={`flex flex-col gap-4 ${fill ? "min-h-0 flex-1" : ""}`}>
      <div className={`flex flex-col gap-5 ${fill ? "min-h-0 flex-1 overflow-y-auto pr-1" : ""}`} aria-live="polite">
        {history.isLoading && <div className="flex items-center gap-2 text-sm text-ink-muted"><Spinner />Loading conversation…</div>}
        {!history.isLoading && messages.length === 0 && suggestions.length > 0 && canAsk && (
          <div className="flex flex-col gap-2">
            <div className="sub">Try asking</div>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => <button key={s} className="btn btn-sm h-auto py-1.5 text-left font-normal" onClick={() => ask(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <Bubble key={i} m={m} paperMap={paperMap}
            actions={actions && m.role === "assistant" && m.content && !(busy && i === messages.length - 1) ? actions(m) : undefined} />
        ))}
        {busy && pending[1]?.content === "" && <div className="flex items-center gap-2 text-sm text-ink-muted"><Spinner />Reading your papers…</div>}
        {error && <div className="rounded-[10px] bg-[#FBEFEE] px-3 py-2 text-sm text-[#7F1D1D]" role="alert">{error}</div>}
        <div ref={end} />
      </div>
      {canAsk ? (
        <form onSubmit={submit} className="flex flex-none items-end gap-2 rounded-card border border-line bg-white p-2 focus-within:border-teal">
          <label className="sr-only" htmlFor={inputId}>Your question</label>
          <textarea id={inputId} rows={2} value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(text); } }}
            placeholder={placeholder ?? "Ask a question about your papers"} className="min-h-[44px] flex-1 resize-none border-0 bg-transparent px-2 py-1.5 text-[15px] outline-none" />
          {busy
            ? <button type="button" className="btn btn-sm h-9 w-9 p-0" onClick={() => abort.current?.abort()} aria-label="Stop"><Square size={14} /></button>
            : <button type="submit" className="btn btn-primary h-9 w-9 p-0" disabled={text.trim().length < 2} aria-label="Send"><ArrowUp size={18} /></button>}
        </form>
      ) : <div className="text-[13px] text-ink-muted">You have view-only access to this session.</div>}
      <div className="flex-none text-xs text-ink-muted">Uses only your kept papers (full text where available, otherwise the abstract). Check the paper before citing.</div>
    </div>
  );
}
