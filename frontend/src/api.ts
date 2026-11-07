// Small typed client for the FastAPI backend. Auth is an httpOnly cookie, so
// requests just include credentials; no token handling in the browser.
import type {
  AppConfig, ChatMessage, Citation, Discovery, Example, Gap, Member, Paper, Screening, Section, SessionInfo,
  SourceStatus, Themes, User, Writing, Feedback,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg || `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const R = "/api/v1/research";
const W = "/api/v1/web";
const S = (id: number) => `${R}/sessions/${id}`;

export const api = {
  config: () => request<AppConfig>("GET", `${W}/config`),
  me: () => request<User>("GET", `${W}/me`),
  login: (email: string, password: string) => request<User>("POST", `${W}/login`, { email, password }),
  register: (b: { email: string; password: string; full_name?: string; invite_code?: string }) =>
    request<User>("POST", `${W}/register`, b),
  logout: () => request<void>("POST", `${W}/logout`),

  sources: () => request<SourceStatus[]>("GET", `${R}/sources`),
  sessions: () => request<SessionInfo[]>("GET", `${R}/sessions`),
  createSession: (topic: string, title?: string) => request<SessionInfo>("POST", `${R}/sessions`, { topic, title }),
  session: (id: number) => request<SessionInfo & { discovery: Discovery | null; screening: Screening }>("GET", S(id)),
  deleteSession: (id: number) => request<void>("DELETE", S(id)),
  papers: (id: number) => request<Paper[]>("GET", `${S(id)}/papers`),
  upload: (id: number, file: File, attachTo?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    const q = attachTo ? `?attach_to=${attachTo}` : "";
    return request<{ paper_id: number; title: string; attached: boolean }>("POST", `${S(id)}/upload${q}`, fd);
  },
  updatePaper: (id: number, paperId: number, patch: Partial<Pick<Paper, "status" | "is_key" | "notes" | "removed_reason">>) =>
    request<Paper>("PATCH", `${S(id)}/papers/${paperId}`, patch),
  addByDoi: (id: number, doi: string) => request<Paper>("POST", `${S(id)}/papers/doi`, { doi }),
  analysis: (id: number) => request<{ discovery: Discovery | null; analysis: Themes | null }>("GET", `${S(id)}/analysis`),
  regenerateThemes: (id: number) => request<Themes>("POST", `${S(id)}/themes`),

  gaps: (id: number) => request<Gap[]>("GET", `${S(id)}/gaps`),
  suggestGaps: (id: number) => request<unknown>("POST", `${S(id)}/gaps`),
  addGap: (id: number, title: string, description: string, assess: boolean) =>
    request<Gap>("POST", `${S(id)}/gaps/custom`, { title, description, assess }),
  updateGap: (id: number, gapId: number, patch: Partial<Pick<Gap, "pinned" | "status" | "notes">>) =>
    request<Gap>("PATCH", `${S(id)}/gaps/${gapId}`, patch),
  assessGap: (id: number, gapId: number) => request<Gap>("POST", `${S(id)}/gaps/${gapId}/assess`),
  deleteGap: (id: number, gapId: number) => request<void>("DELETE", `${S(id)}/gaps/${gapId}`),

  messages: (id: number, gapId?: number) =>
    request<ChatMessage[]>("GET", `${S(id)}/messages${gapId ? `?gap_id=${gapId}` : ""}`),

  writing: (id: number) => request<Writing>("GET", `${S(id)}/writing`),
  outline: (id: number) => request<Section[]>("POST", `${S(id)}/writing/outline`),
  saveSection: (id: number, sectionId: number, user_text: string, heading?: string) =>
    request<Section>("PUT", `${S(id)}/writing/sections/${sectionId}`, { user_text, heading }),
  checkSection: (id: number, sectionId: number) =>
    request<Feedback>("POST", `${S(id)}/writing/sections/${sectionId}/check`),
  addSection: (id: number, heading: string) => request<Section>("POST", `${S(id)}/writing/sections`, { heading }),
  deleteSection: (id: number, sectionId: number) => request<void>("DELETE", `${S(id)}/writing/sections/${sectionId}`),
  moveSection: (id: number, sectionId: number, direction: -1 | 1) =>
    request<Section[]>("POST", `${S(id)}/writing/sections/${sectionId}/move`, { direction }),
  setTitle: (id: number, title: string) => request<{ title: string }>("PUT", `${S(id)}/writing/title`, { title }),
  example: (id: number) => request<Example | null>("GET", `${S(id)}/writing/example`),
  makeExample: (id: number) => request<Example>("POST", `${S(id)}/writing/example`),
  exportUrl: (id: number, style: string, format: "docx" | "pdf") =>
    `${S(id)}/writing/export?style=${encodeURIComponent(style)}&format=${format}`,

  members: (id: number) => request<Member[]>("GET", `${S(id)}/members`),
  share: (id: number, email: string, role: string) => request<unknown>("POST", `${S(id)}/share`, { email, role }),
  removeMember: (id: number, userId: number) => request<void>("DELETE", `${S(id)}/members/${userId}`),
};

/** POST and read a server-sent event stream (fetch-based, so cookies and POST bodies work). */
export async function streamSSE<E>(url: string, body: unknown, onEvent: (e: E) => void,
                                   signal?: AbortSignal): Promise<void> {
  const res = await fetch(url, {
    method: "POST", credentials: "same-origin", signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch { /* ignore */ }
    throw new ApiError(res.status, msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as E);
      }
    }
  }
}

export type AnalyseEvent = { type: "progress"; message: string } | { type: "done"; stats: Discovery }
  | { type: "error"; message: string };
export type ChatEvent = { type: "token"; text: string }
  | { type: "done"; answer: string; citations: Citation[] } | { type: "error"; message: string };
export const analyseUrl = (id: number) => `${S(id)}/analyse/stream`;
export const chatUrl = (id: number) => `${S(id)}/chat/stream`;
