// Shared UI literals for Epic 3 screens. Keep in sync with the API contract;
// the frontend never imports Python — these mirror the pipeline vocabulary.

export type RunStatus = "running" | "awaiting_approval" | "complete" | "failed"

export type GateState = "pending" | "approved" | "rejected" | "n/a" | "failed"

export type StageName = "scenario" | "image" | "tts" | "subtitle" | "video"

export type AbVariant = "A" | "B"

// Mirrors what eval_service.store_evaluation_results actually persists to
// Run.ab_result. CORRECTED IN STORY 13.2: this type previously said `llm_scores` /
// `rule_scores` with keys `scene_count_match` / `subtitle_sync`, none of which the
// backend has ever written — so every score cell rendered "—" on real data, and the
// page's own test fixture used the invented shape and hid it. The backend is
// authoritative; these names are copied from `_axis_scores_to_dict` /
// `_rule_metrics_to_dict`.
// No "total": `_axis_scores_to_dict` emits the three axes only. Declaring a key the
// backend never writes is the same defect this type was corrected to fix.
export type AbAxis = "atmosphere" | "narrative_coherence" | "article_fidelity"

// Story 13.2 added the motion pair (always present) and the visual pair (present only
// when scripts/score_shot_narration.py --dsg ran for that run — absence is expressed by
// omitting the key, never by a 0.0 that would read as perfect readability).
export type AbRuleMetric =
  | "scene_count_match_rate"
  | "subtitle_sync_error"
  | "audio_duration_variance"
  | "cut_alignment_error"
  | "motion_archetype_coverage"
  | "motion_repeat_ratio"
  | "unreadable_rate"
  | "mean_dsg_score"

export type AbResult = {
  winner: AbVariant | "tie" | null
  reason?: string
  axis_scores?: Partial<Record<AbVariant, Partial<Record<AbAxis, number>>>>
  rule_based_scores?: Partial<Record<AbVariant, Partial<Record<AbRuleMetric, number>>>>
  pairwise_winner?: { majority_winner?: string; majority_count?: number; total_runs?: number }
  langfuse_eval_trace_url?: string | null
  evaluated_at?: string
}

// Mirrors RunRead from the Epic 2 API (src/yt_flow/api/routes/runs.py).
export type Run = {
  id: string
  scp_id: string
  status: RunStatus
  current_stage: StageName | null
  gate_states: string | Partial<Record<StageName, GateState>> | null
  prompt_variant?: string | null
  ab_pair_id?: string | null
  ab_result?: AbResult | null
  error?: string | null
  started_at: string
  updated_at: string
  langfuse_trace_url?: string | null
}

// Mirrors ScpEntry from GET /scps (src/yt_flow/api/routes/scps.py). That endpoint
// returns summary fields only; scp_text/tags are optional here and, when absent,
// run creation surfaces the documented API gap instead of sending fake text.
export type ScpEntry = {
  id: string
  nickname: string
  object_class: string
  rating: number
  scp_text?: string
  tags?: string[]
}

// ── Character Management (Story 3.7) ───────────────────────────────────────

export type AngleName = "front" | "back" | "side" | "three_quarter"

export type Character = {
  id: string
  scp_id: string
  canonical_name: string
  aliases: string[]
  visual_descriptor: string | null
  style_guide: string | null
  image_prompt_base: string | null
  selected_image_path: string | null
  angle_front_path: string | null
  angle_back_path: string | null
  angle_side_path: string | null
  angle_three_quarter_path: string | null
  created_at: string
  updated_at: string
}

export type CharacterDetail = Character & {
  references: ReferenceImage[]
  candidates: CharacterCandidate[]
}

export type ReferenceImage = {
  id: string
  character_id: string
  url: string
  local_path: string
  width: number | null
  height: number | null
  created_at: string
}

export type CharacterCandidate = {
  id: string
  character_id: string | null
  scp_id: string
  angle: AngleName
  candidate_num: number
  status: "pending" | "generating" | "ready" | "failed"
  image_path: string | null
  created_at: string
  updated_at: string
}

export type CandidateBatchResponse = {
  candidates: CharacterCandidate[]
  message: string
}
