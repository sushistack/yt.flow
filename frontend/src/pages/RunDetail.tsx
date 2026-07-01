import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { GateState, Run, StageName } from "@/lib/types"
import {
  getRun,
  getStageArtifacts,
  parseGateStates,
  fileUrl,
  STAGE_ORDER,
  type StageArtifacts,
  type ImageArtifacts,
} from "@/lib/api"
import { navigate } from "@/lib/navigate"
import { StatusBadge, StageSidebarItem } from "@/components/common"
import { ArtifactPanel } from "@/components/ArtifactPanel"
import { ImageLightbox } from "@/components/ImageLightbox"
import { useRunProgress } from "@/hooks/useRunProgress"

// Run Detail: two-column layout (240px stage sidebar + artifact panel), live
// sidebar state from SSE, per-stage artifact preview. Read-only surface —
// gate/retry/edit actions land in Story 3.5. [AC1–9]
export function RunDetail({ runId }: { runId: string }) {
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<StageName>("scenario")
  const [artifacts, setArtifacts] = useState<StageArtifacts | null>(null)
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)
  const [hasDirtyEdit, setHasDirtyEdit] = useState(false)
  const mainRef = useRef<HTMLElement>(null)

  // Fetch run metadata; default the selected stage to the furthest one reached.
  useEffect(() => {
    let alive = true
    getRun(runId)
      .then((r) => {
        if (!alive) return
        setRun(r)
        setSelected(r.current_stage ?? "scenario")
      })
      .catch((e) => alive && setError(String(e)))
    return () => {
      alive = false
    }
  }, [runId])

  const gateStates = parseGateStates(run?.gate_states ?? null)
  const curIdx = run?.current_stage ? STAGE_ORDER.indexOf(run.current_stage) : -1
  const reachedIdx = run?.status === "complete" ? STAGE_ORDER.length - 1 : curIdx
  const isReached = (stage: StageName) => STAGE_ORDER.indexOf(stage) <= reachedIdx

  // Load artifacts for the selected stage once it is reachable (404 → null empty state).
  useEffect(() => {
    if (!run) return
    if (!isReached(selected)) {
      setArtifacts(null)
      return
    }
    let alive = true
    setArtifacts(null)
    getStageArtifacts(runId, selected)
      .then((a) => alive && setArtifacts(a))
      .catch(() => alive && setArtifacts(null))
    return () => {
      alive = false
    }
    // reachedIdx captures run status/current_stage changes that flip reachability.
  }, [runId, selected, run, reachedIdx])

  const setStageGateState = useCallback((stage: StageName, gateState: GateState) => {
    setRun((r) => {
      if (!r) return r
      const gs = { ...parseGateStates(r.gate_states), [stage]: gateState }
      return { ...r, gate_states: gs, status: gateState === "pending" ? "awaiting_approval" : r.status }
    })
  }, [])

  const markStageRunning = useCallback((stage: StageName) => {
    setRun((r) => {
      if (!r) return r
      const gs = { ...parseGateStates(r.gate_states), [stage]: "n/a" as GateState }
      return { ...r, status: "running", current_stage: stage, gate_states: gs }
    })
    setArtifacts(null)
  }, [])

  const progressHandlers = useMemo(
    () => ({
      onStageEntry: ({ stage }: { stage?: StageName }) => {
        if (stage) markStageRunning(stage)
      },
      onStageExit: ({ stage }: { stage?: StageName }) => {
        if (stage) setRun((r) => (r ? { ...r, status: "running", current_stage: stage } : r))
      },
      onGatePending: ({ stage }: { stage?: StageName }) => {
        if (stage) setStageGateState(stage, "pending")
      },
      onRunFailed: ({ error: err }: { error?: string }) => {
        setRun((r) => (r ? { ...r, status: "failed", error: err } : r))
      },
      onConnectionError: () => {
        // EventSource auto-retries; only run_failed is authoritative failure.
      },
    }),
    [markStageRunning, setStageGateState],
  )

  useRunProgress(runId, progressHandlers)

  function selectStage(stage: StageName) {
    if (hasDirtyEdit && !window.confirm("저장하지 않은 변경사항이 있습니다. 계속하시겠습니까?")) return
    setHasDirtyEdit(false)
    setSelected(stage)
    mainRef.current?.scrollTo?.(0, 0)
  }

  if (error) return <p className="p-8 text-status-failed">런을 불러올 수 없습니다: {error}</p>
  if (!run) return <p className="p-8 text-muted-foreground">불러오는 중…</p>

  const images = artifacts?.stage === "image" ? (artifacts as ImageArtifacts).images : []

  return (
    <div className="flex min-h-screen flex-col">
      <nav className="flex items-center gap-3 border-b border-border px-6 py-3">
        <button
          type="button"
          onClick={() => navigate("/")}
          className="text-[15px] font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          yt.flow
        </button>
        <span className="text-subtle-foreground">/</span>
        <span className="font-mono text-[12px] font-bold text-foreground">{run.scp_id}</span>
        <StatusBadge status={run.status} />
        <span className="ml-auto" />
        {run.langfuse_trace_url && (
          <a
            href={run.langfuse_trace_url}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            Langfuse 트레이스 ↗
          </a>
        )}
        <button
          type="button"
          onClick={() => navigate(`/runs/${run.id}/ab`)}
          className="rounded-md px-3 py-1.5 text-[12px] text-primary hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          A/B 비교
        </button>
      </nav>

      <div className="flex flex-1">
        <aside className="w-60 shrink-0 border-r border-border py-3">
          <ul>
            {STAGE_ORDER.map((stage) => (
              <li key={stage}>
                <StageSidebarItem
                  stage={stage}
                  active={stage === selected}
                  reached={isReached(stage)}
                  gateState={gateStates[stage] ?? "n/a"}
                  onSelect={selectStage}
                />
              </li>
            ))}
          </ul>
        </aside>

        <main ref={mainRef} className="flex-1 overflow-auto p-6">
          <ArtifactPanel
            runId={runId}
            stage={selected}
            data={artifacts}
            gateState={gateStates[selected] ?? "n/a"}
            onOpenImage={setLightboxIndex}
            onGateStateChange={setStageGateState}
            onRetryStart={markStageRunning}
            onDirtyChange={setHasDirtyEdit}
          />
        </main>
      </div>

      {lightboxIndex !== null && images.length > 0 && (
        <ImageLightbox
          images={images.map((img) => ({
            src: fileUrl(img.image_path),
            alt: `씬 ${img.scene_num} · ${img.shot_id}`,
          }))}
          index={lightboxIndex}
          onIndexChange={setLightboxIndex}
          onClose={() => setLightboxIndex(null)}
        />
      )}
    </div>
  )
}
