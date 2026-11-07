export interface User { id: number; email: string; full_name: string | null; invite_required: boolean }
export interface AppConfig { invite_required: boolean; app_name: string }
export interface SourceStatus { name: string; label: string; mode: "full" | "limited"; key: string; detail: string }

export type Role = "owner" | "lead" | "contributor" | "reviewer" | "viewer";
export interface SessionInfo {
  id: number; title: string; topic: string | null; role: Role; can_edit: boolean; can_manage: boolean;
  paper_count: number; theme_count: number; gap_count: number; words?: number; created_at: string; updated_at: string | null;
}
export interface SourceRun { label: string; mode: "full" | "limited"; found: number; errors: number }
export interface Discovery {
  topic: string; domain: string; queries: string[]; sources: Record<string, SourceRun>;
  candidates: number; added: number; total_in_session?: number; error?: string; ran_at?: string;
}
export interface Paper {
  id: number; n: number; title: string; authors: string[]; year: number | null; journal: string | null;
  doi: string | null; url: string | null; abstract: string | null; citations: number; found_in: string[];
  uploaded: boolean;
  status: "kept" | "removed"; is_key: boolean; notes: string | null; removed_reason: string | null;
  full_text: boolean; full_text_source: string | null; added_at: string | null;
  added_by: number | null; status_by: number | null;
}
export interface Screening {
  screened: number | null; found: number; kept: number; removed: number; key: number;
  removed_reasons: Record<string, number>;
}
export const REMOVE_REASONS: { value: string; label: string }[] = [
  { value: "off_topic", label: "Off-topic" }, { value: "wrong_population", label: "Wrong population" },
  { value: "wrong_study_type", label: "Wrong study type" }, { value: "not_peer_reviewed", label: "Not peer-reviewed" },
  { value: "duplicate", label: "Duplicate" }, { value: "other", label: "Other" },
];
export interface Theme {
  label: string; summary: string; key_findings: string[]; key_paper_ids: number[]; paper_ids: number[];
  top_authors: string[]; year_range: [number, number] | null; size: number;
}
export interface Themes { overview?: string; themes?: Theme[] }

export interface EvidenceItem { paper_id: number; n: number; title: string; why: string }
export interface ClosestPaper { title: string; year: string | null; url: string | null; why: string }
export interface Assessment {
  evidence: { supporting: EvidenceItem[]; contradicting: EvidenceItem[]; summary: string; research_question?: string };
  novelty: { verdict: "open" | "partially_addressed" | "addressed" | "unknown"; explanation: string; closest: ClosestPaper[]; searched?: number };
  checked_at: string;
}
export type GapStatus = "open" | "exploring" | "promising" | "dropped";
export interface Gap {
  id: number; title: string; description: string | null; gap_type: string | null; research_question: string | null;
  confidence: string | null; evidence_paper_ids: number[]; source: "ai" | "user"; pinned: boolean;
  status: GapStatus; notes: string | null; assessment: Assessment | null; created_by?: number | null;
}

export interface Citation { n: number; paper_id: number; title: string; url: string | null; year: number | null }
export interface ChatMessage { role: "user" | "assistant"; content: string; citations: Citation[] | null; created_at: string }

export interface GuidancePoint { text: string; refs: number[] }
export interface Guidance {
  points: GuidancePoint[]; agreements: string[]; disagreements: string[]; questions: string[]; target_words: number | null;
}
export interface Feedback {
  uncited_claims: { sentence: string; suggested_refs: number[]; why: string }[];
  citation_issues: { sentence: string; ref: number; issue: string }[];
  missing_points: string[]; strengths: string[]; summary: string; unknown_refs: number[]; words: number;
  removed_refs?: { n: number; title: string; reason: string | null }[];
  target_words: number | null;
}
export interface Section {
  id: number; position: number; heading: string; kind: string; guidance: Guidance | null;
  user_text: string | null; feedback: Feedback | null; words: number;
  owner_id: number | null; version: number; updated_by: number | null; updated_at: string | null;
}
// ── Working together ────────────────────────────────────────────────────────
export interface CollabMember { id: number; name: string; email: string; role: string; can_edit: boolean }
export interface Proposal {
  id: number; kind: "remove_paper" | "restore_paper" | "untrack_gap" | "delete_gap" | "delete_section";
  target_id: number; payload: { reason?: string }; reason_text: string | null; status: string;
  proposed_by: number; proposed_by_name: string; decided_by: number | null; decided_by_name: string | null; created_at: string;
}
export interface Suggestion {
  id: number; section_id: number; base_text: string; new_text: string; note: string | null;
  user_id: number; user_name: string; status: string; created_at: string;
}
export interface Presence { user_id: number; name: string; where: string }
export interface CollabState {
  members: CollabMember[]; collaborative: boolean; me: number;
  proposals: Proposal[]; suggestions: Suggestion[]; present: Presence[];
}
export interface CommentItem { id: number; user_id: number; user_name: string; body: string; mentions: number[]; created_at: string }
export interface CommentThread extends CommentItem {
  target_type: string; target_id: number; quote: string | null; resolved: boolean; replies: CommentItem[];
}
export interface ActivityItem {
  id: number; kind: string; summary: string; user_id: number | null; user_name: string | null;
  target_type: string | null; target_id: number | null; data: Record<string, unknown> | null; at: string;
}
export interface NeedsYou {
  type: "proposal" | "suggestion" | "mention"; id: number; user_name: string; text: string; at: string;
  kind?: string; target_id?: number; target_type?: string; section_id?: number;
}
export interface WhatsNew { last_seen_at: string | null; needs_you: NeedsYou[]; changes: ActivityItem[]; unseen: number; count: number }

export interface NoticeAction { label: string; to?: string; ask?: string; gap_id?: number }
export interface Notice { id: string; text: string; actions: NoticeAction[] }
/** What the research partner panel is about. */
export type PartnerContext =
  | { kind: "session" }
  | { kind: "gap"; id: number; title: string }
  | { kind: "theme"; index: number; label: string }
  | { kind: "section"; id: number; heading: string };
export interface Changes {
  papers_added: number; papers_removed: number; key_changed: number; gaps_tracked: number; gaps_untracked: number; summary: string;
}
export interface Writing { title: string; sections: Section[]; guide_changes: Changes | null }
export interface Example { title: string; sections: { heading: string; paragraphs: string[] }[]; references: string[]; style: string }
export interface Member { user_id: number; email: string; full_name: string | null; role: string }
