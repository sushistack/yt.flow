// Shared UI literals for Epic 3 screens. Keep in sync with the API contract;
// the frontend never imports Python — these mirror the pipeline vocabulary.

export type RunStatus = "running" | "awaiting_approval" | "complete" | "failed"

export type GateState = "pending" | "approved" | "rejected" | "n/a"

export type StageName = "scenario" | "image" | "tts" | "subtitle" | "video"

// Mirrors RunRead from the Epic 2 API (src/yt_flow/api/routes/runs.py).
export type Run = {
  id: string
  scp_id: string
  status: RunStatus
  current_stage: StageName | null
  gate_states: string | null
  prompt_variant?: string | null
  ab_pair_id?: string | null
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
