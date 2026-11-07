export interface User { id: number; email: string; full_name: string | null; invite_required: boolean }
export interface AppConfig { invite_required: boolean; app_name: string }
export interface SourceStatus { name: string; label: string; mode: "full" | "limited"; key: string; detail: string }

export type Role = "owner" | "lead" | "contributor" | "reviewer" | "viewer";
export interface SessionInfo {
  id: number; title: string; topic: string | null; role: Role; can_edit: boolean; can_manage: boolean;
  paper_count: number; theme_count: number; gap_count: number; created_at: string; updated_at: string | null;
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
}
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
  status: GapStatus; notes: string | null; assessment: Assessment | null;
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
  target_words: number | null;
}
export interface Section {
  id: number; position: number; heading: string; kind: string; guidance: Guidance | null;
  user_text: string | null; feedback: Feedback | null; words: number;
}
export interface Writing { title: string; sections: Section[] }
export interface Example { title: string; sections: { heading: string; paragraphs: string[] }[]; references: string[]; style: string }
export interface Member { user_id: number; email: string; full_name: string | null; role: string }
