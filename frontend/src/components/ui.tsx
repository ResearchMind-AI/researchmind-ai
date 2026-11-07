import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { Loader2, X } from "lucide-react";
import type { Paper } from "../types";

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 34 34" aria-hidden="true">
      <rect width="34" height="34" rx="9" fill="#0F766E" />
      <circle cx="11" cy="12" r="3" fill="#fff" />
      <circle cx="23" cy="11" r="3" fill="#fff" />
      <circle cx="17" cy="23" r="3" fill="#5EEAD4" />
      <path d="M11 12 L23 11 L17 23 Z" fill="none" stroke="#fff" strokeWidth="1.6" />
    </svg>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return <Loader2 className={`spin ${className}`} size={16} aria-hidden="true" />;
}

export function PageLoading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-ink-muted" role="status">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="rounded-xl border border-[#E8C4C0] bg-[#FBEFEE] px-4 py-3 text-[#7F1D1D]" role="alert">{msg}</div>;
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center gap-3 px-6 py-14 text-center">
      {icon && <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-teal-soft text-teal-ink">{icon}</div>}
      <div className="h-serif text-xl">{title}</div>
      {children && <div className="max-w-md text-ink-muted">{children}</div>}
    </div>
  );
}

/** Text with [n] citations rendered as badges linking to the paper. Supports markdown. */
export function CitedText({ text, papers, markdown = false }: { text: string; papers?: Map<number, Paper>; markdown?: boolean }) {
  const linked = text.replace(/\[(\d+)\]/g, (_m, n) => `[${n}](#ref-${n})`);
  const components = {
    a: ({ href, children }: { href?: string; children?: ReactNode }) => {
      const m = href?.match(/^#ref-(\d+)$/);
      if (!m) return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
      const p = papers?.get(Number(m[1]));
      const label = p ? `${p.title}${p.year ? ` (${p.year})` : ""}` : `Paper ${m[1]}`;
      return p?.url
        ? <a className="ref" href={p.url} target="_blank" rel="noreferrer" title={label} aria-label={`Source ${m[1]}: ${label}`}>{m[1]}</a>
        : <span className="ref" title={label}>{m[1]}</span>;
    },
    p: ({ children }: { children?: ReactNode }) => (markdown ? <p>{children}</p> : <>{children}</>),
  };
  return (
    <span className={markdown ? "prose-answer block" : ""}>
      <ReactMarkdown components={components as never}
        allowedElements={markdown ? undefined : ["p", "a", "strong", "em", "code"]} unwrapDisallowed>
        {linked}
      </ReactMarkdown>
    </span>
  );
}

export function RefBadges({ refs, papers }: { refs: number[]; papers?: Map<number, Paper> }) {
  if (!refs.length) return null;
  return <span className="ml-1 inline-flex flex-wrap gap-1">{refs.map((n) => <CitedText key={n} text={`[${n}]`} papers={papers} />)}</span>;
}

// ── Toasts ─────────────────────────────────────────────────────────────────
type Toast = { id: number; text: string; tone: "ok" | "error" };
const ToastCtx = createContext<(text: string, tone?: "ok" | "error") => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 6000 : 2800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-5 left-5 z-50 flex flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`flex max-w-sm items-start gap-3 rounded-xl px-4 py-3 text-sm shadow-lg ${t.tone === "error" ? "bg-[#7F1D1D] text-white" : "bg-navy text-white"}`}>
            <span className="flex-1">{t.text}</span>
            <button className="text-white/70 hover:text-white" aria-label="Dismiss" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}><X size={16} /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-navy/50 px-4 py-16" role="dialog" aria-modal="true" aria-label={title}
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="card w-full max-w-lg p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="h-serif text-2xl">{title}</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}
