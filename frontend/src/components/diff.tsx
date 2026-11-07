// Word-level diff for suggested edits: shows removed words struck through and added words underlined.
type Part = { kind: "same" | "add" | "del"; text: string };

export function wordDiff(a: string, b: string): Part[] {
  const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
  // Guard against very long sections: fall back to "whole text replaced".
  if (A.length * B.length > 4_000_000) return [{ kind: "del", text: a }, { kind: "add", text: b }];
  const n = A.length, m = B.length;
  const L: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: Part[] = [];
  const push = (kind: Part["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text; else out.push({ kind, text });
  };
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { push("same", A[i]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) push("del", A[i++]);
    else push("add", B[j++]);
  }
  while (i < n) push("del", A[i++]);
  while (j < m) push("add", B[j++]);
  return out;
}

export function Diff({ from, to, color = "#9A3412" }: { from: string; to: string; color?: string }) {
  return (
    <span className="whitespace-pre-wrap">
      {wordDiff(from, to).map((p, k) =>
        p.kind === "same" ? <span key={k}>{p.text}</span>
          : p.kind === "add" ? <ins key={k} className="bg-[#FDE7D8] underline decoration-2" style={{ color }}>{p.text}</ins>
          : <del key={k} className="bg-[#FDE7D8]" style={{ color }}>{p.text}</del>)}
    </span>
  );
}
