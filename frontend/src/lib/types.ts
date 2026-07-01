// Shared UI literals for Epic 3 screens. Keep in sync with the API contract;
// the frontend never imports Python — these mirror the pipeline vocabulary.

export type RunStatus = "running" | "awaiting_approval" | "complete" | "failed"

export type GateState = "pending" | "approved" | "rejected" | "n/a" | "failed"

export type StageName = "scenario" | "image" | "tts" | "subtitle" | "video"

export type AbVariant = "A" | "B"

export type AbResult = {
  winner: AbVariant | "tie" | null
  reason?: string
  llm_scores?: Partial<Record<AbVariant, Partial<Record<"atmosphere" | "narrative_coherence" | "article_fidelity", number>>>>
  rule_scores?: Partial<
    Record<AbVariant, Partial<Record<"scene_count_match" | "subtitle_sync" | "audio_duration_variance", number>>>
  >
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
