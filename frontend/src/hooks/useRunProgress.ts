import { useEffect } from "react"
import type { StageName } from "@/lib/types"

export type ProgressEventData = {
  run_id: string
  stage?: StageName
  error?: string
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
