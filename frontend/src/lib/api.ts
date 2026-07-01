import type { GateState, Run, ScpEntry, StageName } from "@/lib/types"

// Single place that assembles URLs and parses responses. Components never fetch
// ad hoc. Same-origin: the SPA is served by FastAPI, so relative paths work and
// no base URL is needed (Architecture: HTTP-only, no direct file/db access).
export class ApiError extends Error {}

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
  if (!res.ok) throw new ApiError(`${init?.method ?? "GET"} ${path} → ${res.status}`)
  return res.json() as Promise<T>
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

// Artifact paths point somewhere under the workspace mount. Keep the browser URL
// rooted at the run directory, even when the backend returns an absolute path
// whose workspace folder has a custom name.
export function fileUrl(serverPath: string): string {
  const normalized = serverPath.replaceAll("\\", "/").replace(/^\.?\//, "")
  if (normalized.startsWith("workspace/")) return `/files/${normalized.slice("workspace/".length)}`
  const marker = normalized.match(/(?:^|\/)([^/]+)\/(images|audio|subs|subtitles|video|output)\//)
  if (marker?.index != null) return `/files/${normalized.slice(marker.index).replace(/^\//, "")}`
  const runFile = normalized.match(/(?:^|\/)([^/]+)\/(?:output\.mp4|video\.mp4)$/)
  if (runFile?.index != null) return `/files/${normalized.slice(runFile.index).replace(/^\//, "")}`
  const workspaceIdx = normalized.lastIndexOf("/workspace/")
  if (workspaceIdx >= 0) return `/files/${normalized.slice(workspaceIdx + "/workspace/".length)}`
  return `/files/${normalized.replace(/^.*\//, "")}`
}

export const videoDownloadUrl = (id: string) => `/runs/${id}/artifact`

export function parseGateStates(raw: string | null): Partial<Record<StageName, GateState>> {
  if (!raw) return {}
  try {
    return JSON.parse(raw)
  } catch {
    return {}
  }
}
