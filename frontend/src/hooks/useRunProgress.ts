import { useEffect } from "react"
import type { ScenarioQuality } from "@/lib/api"
import type { StageName } from "@/lib/types"

export type ProgressEventData = {
  run_id: string
  stage?: StageName
  error?: string
  // Story 12.3: only `gate_pending` for the scenario stage carries this, and only
  // as acceleration — the artifact endpoint is the durable authority, so a client
  // that missed the frame recovers by fetching artifacts.
  scenario_quality?: ScenarioQuality | null
}

export type RunProgressHandlers = {
  onStageEntry?: (event: ProgressEventData) => void
  onStageExit?: (event: ProgressEventData) => void
  onGatePending?: (event: ProgressEventData) => void
  onRunFailed?: (event: ProgressEventData) => void
  onConnectionError?: () => void
}

function parseEvent(event: MessageEvent): ProgressEventData | null {
  try {
    return JSON.parse(event.data) as ProgressEventData
  } catch {
    return null // malformed SSE payload — ignore, don't crash
  }
}

export function useRunProgress(runId: string, handlers: RunProgressHandlers) {
  useEffect(() => {
    const es = new EventSource(`/runs/${runId}/progress`)
    const stageEntry = (event: Event) => {
      const data = parseEvent(event as MessageEvent)
      if (data) handlers.onStageEntry?.(data)
    }
    const stageExit = (event: Event) => {
      const data = parseEvent(event as MessageEvent)
      if (data) handlers.onStageExit?.(data)
    }
    const gatePending = (event: Event) => {
      const data = parseEvent(event as MessageEvent)
      if (data) handlers.onGatePending?.(data)
    }
    const runFailed = (event: Event) => {
      const data = parseEvent(event as MessageEvent)
      if (data) handlers.onRunFailed?.(data)
    }

    es.addEventListener("stage_entry", stageEntry)
    es.addEventListener("stage_exit", stageExit)
    es.addEventListener("gate_pending", gatePending)
    es.addEventListener("run_failed", runFailed)
    es.onerror = () => handlers.onConnectionError?.()

    return () => es.close()
  }, [runId, handlers])
}
