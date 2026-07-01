import { useEffect, useRef, useState } from "react"
import type { Run, StageName } from "@/lib/types"
import {
  ApiError,
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
import { ArtifactPanel, sortImagesByScene } from "@/components/ArtifactPanel"
import { ImageLightbox } from "@/components/ImageLightbox"

// Run Detail: two-column layout (240px stage sidebar + artifact panel), live
// sidebar state from SSE, per-stage artifact preview. Read-only surface —
// gate/retry/edit actions land in Story 3.5. [AC1–9]
export function RunDetail({ runId }: { runId: string }) {
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<StageName>("scenario")
  const [artifacts, setArtifacts] = useState<StageArtifacts | null | undefined>(undefined)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [liveReachedStages, setLiveReachedStages] = useState<Set<StageName>>(() => new Set())
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)
  const mainRef = useRef<HTMLElement>(null)

  // Fetch run metadata; default the selected stage to the furthest one reached.
  useEffect(() => {
    let alive = true
    getRun(runId)
      .then((r) => {
        if (!alive) return
        setRun(r)
        setSelected(r.current_stage ?? "scenario")
        setLiveReachedStages(new Set(reachedStagesFromRun(r)))
      })
      .catch((e) => alive && setError(String(e)))
    return () => {
      alive = false
    }
  }, [runId])

  const gateStates = parseGateStates(run?.gate_states ?? null)
  const curIdx = run?.current_stage ? STAGE_ORDER.indexOf(run.current_stage) : -1
  const reachedIdx = run?.status === "complete" ? STAGE_ORDER.length - 1 : curIdx
  const reachedFromRun = new Set(run ? reachedStagesFromRun(run) : [])
  const isReached = (stage: StageName) =>
    reachedFromRun.has(stage) || liveReachedStages.has(stage) || gateStates[stage] === "pending"

  // Load artifacts for the selected stage once it is reachable (404 → null empty state).
  useEffect(() => {
    if (!run) return
    if (!isReached(selected)) {
      setArtifacts(null)
      setArtifactError(null)
      return
    }
    let alive = true
    setArtifacts(undefined)
    setArtifactError(null)
    getStageArtifacts(runId, selected)
      .then((a) => {
        if (alive) setArtifacts(a)
      })
      .catch((e) => {
        if (!alive) return
        setArtifacts(null)
        setArtifactError(e instanceof ApiError ? e.message : String(e))
      })
    return () => {
      alive = false
    }
    // reachedIdx captures run status/current_stage changes that flip reachability.
  }, [runId, selected, run, reachedIdx, liveReachedStages])

  // Live progress: mutate run state in place, never reload (AC9).
  useEffect(() => {
    const es = new EventSource(`/runs/${runId}/progress`)
    const readStage = (event: MessageEvent): StageName | null => {
      try {
        const stage = JSON.parse(event.data).stage
        return isStageName(stage) ? stage : null
      } catch {
        return null
      }
    }
    const markReached = (stage: StageName) =>
      setLiveReachedStages((prev) => new Set([...prev, stage]))
    const advance = (stage: StageName) => {
      markReached(stage)
      setRun((r) => (r ? { ...r, status: "running", current_stage: stage } : r))
    }
    es.addEventListener("stage_entry", (e) => {
      const stage = readStage(e)
      if (stage) advance(stage)
    })
    es.addEventListener("stage_exit", (e) => {
      const stage = readStage(e)
      if (stage) markReached(stage)
    })
    es.addEventListener("gate_pending", (e) => {
      const stage = readStage(e)
      if (!stage) return
      markReached(stage)
      setRun((r) => {
        if (!r) return r
        const gs = { ...parseGateStates(r.gate_states), [stage]: "pending" }
        return { ...r, status: "awaiting_approval", gate_states: JSON.stringify(gs) }
      })
    })
    es.addEventListener("run_failed", (e) => {
      let err = "알 수 없는 오류"
      try {
        err = JSON.parse(e.data).error ?? err
      } catch {
        // ignore malformed payload; keep a visible generic failure state.
      }
      setRun((r) => (r ? { ...r, status: "failed", error: err } : r))
    })
    return () => es.close()
  }, [runId])

  function selectStage(stage: StageName) {
    setSelected(stage)
    mainRef.current?.scrollTo(0, 0)
  }

  if (error) return <p className="p-8 text-status-failed">런을 불러올 수 없습니다: {error}</p>
  if (!run) return <p className="p-8 text-muted-foreground">불러오는 중…</p>

  const images = artifacts?.stage === "image" ? sortImagesByScene((artifacts as ImageArtifacts).images) : []

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
        {run.langfuse_trace_url && (
          <a
            href={run.langfuse_trace_url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-[12px] text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            Langfuse 트레이스 ↗
          </a>
        )}
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
          {artifactError ? (
            <p role="alert" className="text-status-failed">
              아티팩트를 불러올 수 없습니다: {artifactError}
            </p>
          ) : (
            <ArtifactPanel runId={runId} data={artifacts} onOpenImage={setLightboxIndex} />
          )}
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

function isStageName(value: unknown): value is StageName {
  return typeof value === "string" && STAGE_ORDER.includes(value as StageName)
}

function reachedStagesFromRun(run: Run): StageName[] {
  if (run.status === "complete") return STAGE_ORDER
  if (!run.current_stage) return []
  const index = STAGE_ORDER.indexOf(run.current_stage)
  return index < 0 ? [] : STAGE_ORDER.slice(0, index + 1)
}
