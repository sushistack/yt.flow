// Shared UI literals for Epic 3 screens. Keep in sync with the API contract;
// the frontend never imports Python — these mirror the pipeline vocabulary.

export type RunStatus = "running" | "awaiting_approval" | "complete" | "failed"

export type GateState = "pending" | "approved" | "rejected" | "n/a"

export type StageName = "scenario" | "image" | "tts" | "subtitle" | "video"
