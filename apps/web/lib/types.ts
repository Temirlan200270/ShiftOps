export type UserRole = "owner" | "admin" | "operator" | "bartender";

export type Criticality = "critical" | "required" | "optional";

export type TaskStatus =
  | "pending"
  | "done"
  | "skipped"
  | "waiver_pending"
  | "waived"
  | "waiver_rejected"
  | "obsolete";

export type ShiftStatus =
  | "scheduled"
  | "active"
  | "closed_clean"
  | "closed_with_violations"
  | "aborted";

export interface TaskCard {
  id: string;
  title: string;
  description: string | null;
  section: string | null;
  criticality: Criticality;
  status: TaskStatus;
  requiresPhoto: boolean;
  requiresComment: boolean;
  comment: string | null;
  hasAttachment: boolean;
}

/**
 * Each component is in [0, 1]. Multiply by `SCORE_WEIGHTS` to get the
 * contribution in points (out of 100). Mirrors the backend's
 * `ShiftScoreBreakdown` exactly.
 */
export interface ScoreBreakdown {
  completion: number;
  criticalCompliance: number;
  timeliness: number;
  photoQuality: number;
}

/**
 * Source of truth for the weights — used by the summary screen tooltips.
 * Backend authoritatively computes the score; we use these client-side only
 * for display ("Completion: 47.5 / 50").
 */
export const SCORE_WEIGHTS: Record<keyof ScoreBreakdown, number> = {
  completion: 50,
  criticalCompliance: 25,
  timeliness: 15,
  photoQuality: 10,
};

export interface ShiftSummary {
  id: string;
  templateName: string;
  status: ShiftStatus;
  scheduledStart: string;
  scheduledEnd: string;
  actualStart: string | null;
  actualEnd: string | null;
  score: number | null;
  scoreBreakdown: ScoreBreakdown | null;
  formulaVersion: number | null;
  tasks: TaskCard[];
  /** Operator on the shift (from server; same as current user for /me). */
  operatorFullName: string;
  slotIndex: number;
  stationLabel: string | null;
}
