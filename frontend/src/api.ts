// Small typed client for the FastAPI backend. Auth is an httpOnly cookie, so
// requests just include credentials; no token handling in the browser.
import type {
  ActivityItem, AppConfig, Changes, ChatMessage, CollabState, CommentThread, Notice, Presence, Proposal, Suggestion, WhatsNew, Citation, Discovery, Example, Gap, Member, Paper, Screening, Section, SessionInfo,
  SourceStatus, Themes, User, Writing, Feedback,
} from "./types";

export class ApiError extends Error {
  status: number;
  /** Extra details the server sent with the error (e.g. the current text on a conflict). */
  data: Record<string, unknown> | null;
  constructor(status: number, message: string, data: Record<string, unknown> | null = null) {
    super(message);
    this.status = status;
    this.data = data;
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
    let extra: Record<string, unknown> | null = null;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
      else if (data.detail && typeof data.detail === "object" && "message" in data.detail) { extra = data.detail; msg = String(data.detail.message); }
      else msg = JSON.stringify(data.detail ?? data);
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg || `Request failed (${res.status})`, extra);
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
    request<Paper | { proposal: Proposal; paper: Paper }>("PATCH", `${S(id)}/papers/${paperId}`, patch),
  addByDoi: (id: number, doi: string) => request<Paper>("POST", `${S(id)}/papers/doi`, { doi }),
  analysis: (id: number) => request<{ discovery: Discovery | null; analysis: Themes | null; changes: Changes | null; refresh_due: boolean }>("GET", `${S(id)}/analysis`),
  regenerateThemes: (id: number) => request<Themes>("POST", `${S(id)}/themes`),

  gaps: (id: number) => request<Gap[]>("GET", `${S(id)}/gaps`),
  suggestGaps: (id: number) => request<unknown>("POST", `${S(id)}/gaps`),
  addGap: (id: number, title: string, description: string, assess: boolean) =>
    request<Gap>("POST", `${S(id)}/gaps/custom`, { title, description, assess }),
  notices: (id: number) => request<Notice[]>("GET", `${S(id)}/partner/notices`),
  updateGap: (id: number, gapId: number, patch: Partial<Pick<Gap, "pinned" | "status" | "notes" | "research_question">>) =>
    request<Gap | { proposal: Proposal; gap: Gap }>("PATCH", `${S(id)}/gaps/${gapId}`, patch),
  assessGap: (id: number, gapId: number) => request<Gap>("POST", `${S(id)}/gaps/${gapId}/assess`),
  deleteGap: (id: number, gapId: number) => request<{ proposal: Proposal } | undefined>("DELETE", `${S(id)}/gaps/${gapId}`),

  messages: (id: number, gapId?: number) =>
    request<ChatMessage[]>("GET", `${S(id)}/messages${gapId ? `?gap_id=${gapId}` : ""}`),

  writing: (id: number) => request<Writing>("GET", `${S(id)}/writing`),
  outline: (id: number) => request<Section[]>("POST", `${S(id)}/writing/outline`),
  refreshGuidance: (id: number) => request<{ summary: string; sections: Section[] }>("POST", `${S(id)}/writing/guidance/refresh`),
  saveSection: (id: number, sectionId: number, user_text: string, heading?: string, base_version?: number) =>
    request<Section>("PUT", `${S(id)}/writing/sections/${sectionId}`, { user_text, heading, base_version }),
  checkSection: (id: number, sectionId: number) =>
    request<Feedback>("POST", `${S(id)}/writing/sections/${sectionId}/check`),
  addSection: (id: number, heading: string) => request<Section>("POST", `${S(id)}/writing/sections`, { heading }),
  deleteSection: (id: number, sectionId: number) => request<{ proposal: Proposal } | undefined>("DELETE", `${S(id)}/writing/sections/${sectionId}`),

  // Working together
  collab: (id: number) => request<CollabState>("GET", `${S(id)}/collab`),
  propose: (id: number, b: { kind: string; target_id: number; reason?: string; reason_text?: string }) =>
    request<Proposal>("POST", `${S(id)}/proposals`, b),
  decide: (id: number, proposalId: number, decision: "approve" | "reject" | "withdraw") =>
    request<Proposal>("POST", `${S(id)}/proposals/${proposalId}/decide`, { decision }),
  comments: (id: number, target_type?: string, target_id?: number) =>
    request<CommentThread[]>("GET", `${S(id)}/comments${target_type ? `?target_type=${target_type}${target_id != null ? `&target_id=${target_id}` : ""}` : ""}`),
  addComment: (id: number, b: { target_type?: string; target_id?: number; body: string; quote?: string; parent_id?: number }) =>
    request<{ id: number }>("POST", `${S(id)}/comments`, b),
  resolveComment: (id: number, commentId: number, resolved: boolean) =>
    request<{ id: number; resolved: boolean }>("POST", `${S(id)}/comments/${commentId}/resolve`, { resolved }),
  suggestEdit: (id: number, sectionId: number, text: string, note?: string) =>
    request<Suggestion>("POST", `${S(id)}/writing/sections/${sectionId}/suggestions`, { text, note }),
  decideSuggestion: (id: number, suggestionId: number, decision: "accept" | "reject" | "withdraw") =>
    request<Suggestion>("POST", `${S(id)}/suggestions/${suggestionId}/decide`, { decision }),
  whatsNew: (id: number) => request<WhatsNew>("GET", `${S(id)}/whats-new`),
  seen: (id: number) => request<void>("POST", `${S(id)}/seen`),
  history: (id: number, target_type: string, target_id: number) =>
    request<ActivityItem[]>("GET", `${S(id)}/history?target_type=${target_type}&target_id=${target_id}`),
  presence: (id: number, where: string) => request<Presence[]>("POST", `${S(id)}/presence`, { where }),
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
export const fullTextUrl = (id: number, retry = false) => `${S(id)}/fulltext/stream${retry ? "?retry=true" : ""}`;
