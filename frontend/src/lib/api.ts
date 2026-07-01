import type { GateState, Run, ScpEntry, StageName } from "@/lib/types"

// Single place that assembles URLs and parses responses. Components never fetch
// ad hoc. Same-origin: the SPA is served by FastAPI, so relative paths work and
// no base URL is needed (Architecture: HTTP-only, no direct file/db access).
export class ApiError extends Error {}

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === "string" && body.detail.trim()) return body.detail
  } catch {
    // Fall through to Korean fallback below.
  }
  return fallback
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    })
  } catch {
    // Network failure / server down — distinct from an HTTP error status.
    throw new ApiError("서버에 연결할 수 없습니다")
  }
  if (!res.ok) throw new ApiError(await errorMessage(res, "요청을 처리할 수 없습니다"))
  if (res.status === 204) return undefined as T
  if (typeof res.text !== "function") return res.json() as Promise<T>
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const getRuns = () => json<Run[]>("/runs")

export const getScps = () => json<ScpEntry[]>("/scps")

// scp_text is optional: the server resolves the article text from scp_id, so the
// picker sends scp_id only and never carries the full text (HTTP-only frontend).
export type RunCreate = { scp_id: string; scp_text?: string }

export const createRun = (body: RunCreate) =>
  json<Run>("/runs", { method: "POST", body: JSON.stringify(body) })

// ── Run Detail (Story 3.4) ──────────────────────────────────────────────────

export const STAGE_ORDER: StageName[] = ["scenario", "image", "tts", "subtitle", "video"]

export const getRun = (id: string) => json<Run>(`/runs/${id}`)

// Per-stage artifact DTOs mirror run_service.get_stage_artifacts(). They carry
// server filesystem paths; fileUrl() turns those into /files URLs the browser loads.
export type ScenarioArtifacts = {
  stage: "scenario"
  scenes: { scene_num: number; narration: string }[]
}
export type ImageArtifacts = {
  stage: "image"
  images: { scene_num: number; shot_id: string; image_path: string }[]
}
export type TtsArtifacts = {
  stage: "tts"
  audio: { scene_num: number; audio_path: string; duration_sec: number | null }[]
}
export type SubtitleArtifacts = {
  stage: "subtitle"
  subtitles: { scene_num: number; subtitle_path: string }[]
}
export type VideoArtifacts = { stage: "video"; video_path: string }
export type StageArtifacts =
  | ScenarioArtifacts
  | ImageArtifacts
  | TtsArtifacts
  | SubtitleArtifacts
  | VideoArtifacts

// 404 = stage not yet reached → null (muted empty state, not a page error).
// Own fetch (not json()) so the 404 status is inspectable without a typed error.
export async function getStageArtifacts(id: string, stage: StageName): Promise<StageArtifacts | null> {
  let res: Response
  try {
    res = await fetch(`/runs/${id}/stages/${stage}/artifacts`)
  } catch {
    throw new ApiError("서버에 연결할 수 없습니다")
  }
  if (res.status === 404) return null
  if (!res.ok) throw new ApiError(`GET /runs/${id}/stages/${stage}/artifacts → ${res.status}`)
  return res.json() as Promise<StageArtifacts>
}

// Artifact paths are workspace/{run_id}/...; the /files static mount serves them.
export function fileUrl(serverPath: string): string {
  const parts = serverPath.split(/workspace[\\/]/)
  return "/files/" + parts[parts.length - 1].replace(/^[\\/]+/, "")
}

export const videoDownloadUrl = (id: string) => `/runs/${id}/artifact`

export function parseGateStates(
  raw: string | Partial<Record<StageName, GateState>> | null,
): Partial<Record<StageName, GateState>> {
  if (!raw) return {}
  if (typeof raw === "object") return raw
  try {
    return JSON.parse(raw)
  } catch {
    return {}
  }
}

export type GateActionResponse = Partial<Run> | { gate_state?: GateState; state?: GateState }
export type ArtifactPatchResponse = StageArtifacts | { text?: string; content?: string }

export const approveGate = (id: string, stage: StageName) =>
  json<GateActionResponse>(`/runs/${id}/stages/${stage}/gate`, {
    method: "POST",
    body: JSON.stringify({ action: "approve" }),
  })

export const rejectGate = (id: string, stage: StageName) =>
  json<GateActionResponse>(`/runs/${id}/stages/${stage}/gate`, {
    method: "POST",
    body: JSON.stringify({ action: "reject" }),
  })

export const retryStage = (id: string, stage: StageName) =>
  json<Partial<Run>>(`/runs/${id}/stages/${stage}/retry`, { method: "POST" })

export const patchStageArtifact = (id: string, stage: StageName, text: string) =>
  json<ArtifactPatchResponse>(`/runs/${id}/stages/${stage}/artifact`, {
    method: "PATCH",
    body: JSON.stringify({ body: text }),
  })
