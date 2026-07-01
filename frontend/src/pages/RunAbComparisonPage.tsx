import { useEffect, useState } from "react"
import type { ReactNode } from "react"
import { ArtifactPanel } from "@/components/ArtifactPanel"
import { ImageLightbox } from "@/components/ImageLightbox"
import { StatusBadge } from "@/components/common"
import {
  getRun,
  getRuns,
  getStageArtifacts,
  fileUrl,
  STAGE_ORDER,
  type ImageArtifacts,
  type StageArtifacts,
} from "@/lib/api"
import { navigate } from "@/lib/navigate"
import type { AbResult, AbVariant, Run, StageName } from "@/lib/types"
import { cn } from "@/lib/utils"

type PairState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "missing"; run: Run }
  | { kind: "ready"; a: Run; b: Run }

type LightboxState = { variant: AbVariant; index: number } | null

const LLM_AXES = ["atmosphere", "narrative_coherence", "article_fidelity"] as const
const RULE_METRICS = ["scene_count_match", "subtitle_sync", "audio_duration_variance"] as const

export function RunAbComparisonPage({ runId }: { runId: string }) {
  const [pair, setPair] = useState<PairState>({ kind: "loading" })
  const [selectedStage, setSelectedStage] = useState<StageName>("scenario")
  const [artifacts, setArtifacts] = useState<Partial<Record<AbVariant, StageArtifacts | null>>>({})
  const [lightbox, setLightbox] = useState<LightboxState>(null)

  useEffect(() => {
    let alive = true
    setPair({ kind: "loading" })
    setArtifacts({})

    getRun(runId)
      .then(async (selected) => {
        if (selected.ab_pair_id) {
          const origin = await getRun(selected.ab_pair_id)
          return { kind: "ready", a: origin, b: selected } as PairState
        }

        const runs = await getRuns()
        const paired = runs.find((candidate) => candidate.ab_pair_id === selected.id)
        return paired
          ? ({ kind: "ready", a: selected, b: paired } as PairState)
          : ({ kind: "missing", run: selected } as PairState)
      })
      .then((next) => alive && setPair(next))
      .catch((error) => alive && setPair({ kind: "error", message: String(error) }))

    return () => {
      alive = false
    }
  }, [runId])

  useEffect(() => {
    if (pair.kind !== "ready") return
    let alive = true
    setArtifacts({})

    Promise.all([
      getStageArtifacts(pair.a.id, selectedStage).catch(() => null),
      getStageArtifacts(pair.b.id, selectedStage).catch(() => null),
    ]).then(([a, b]) => {
      if (alive) setArtifacts({ A: a, B: b })
    })

    return () => {
      alive = false
    }
  }, [pair, selectedStage])

  if (pair.kind === "loading") return <p className="p-8 text-muted-foreground">불러오는 중…</p>
  if (pair.kind === "error") return <p className="p-8 text-status-failed">비교 정보를 불러올 수 없습니다: {pair.message}</p>
  if (pair.kind === "missing") {
    return (
      <RouteShell run={pair.run}>
        <main className="p-6">
          <h1 className="text-[20px] font-semibold text-foreground">A/B 비교</h1>
          <p role="status" className="mt-4 text-status-awaiting">
            연결된 B variant가 없습니다
          </p>
        </main>
      </RouteShell>
    )
  }

  const result = pair.a.ab_result ?? pair.b.ab_result ?? null
  const nonSuccess = getNonSuccessState(pair.a, pair.b, result)
  const activeImages = lightbox ? getImages(artifacts[lightbox.variant]) : []

  return (
    <RouteShell run={pair.a}>
      <main className="flex flex-1 flex-col gap-5 p-6">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-[20px] font-semibold text-foreground">A/B 비교</h1>
            <p className="mt-1 font-mono text-[12px] text-subtle-foreground">
              {pair.a.id} / {pair.b.id}
            </p>
          </div>
          {nonSuccess && (
            <StateMessage kind={nonSuccess.kind} message={nonSuccess.message} />
          )}
          {result && !nonSuccess && <WinnerSummary result={result} />}
        </div>

        <div aria-label="비교 스테이지" className="flex gap-1">
          {STAGE_ORDER.map((stage) => (
            <button
              key={stage}
              type="button"
              onClick={() => setSelectedStage(stage)}
              className={cn(
                "rounded-md px-3 py-1.5 text-[12px] text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                selectedStage === stage && "bg-card text-foreground",
              )}
            >
              <span className="font-mono">{stage}</span>
            </button>
          ))}
        </div>

        <section className="grid min-h-0 flex-1 grid-cols-2 gap-5">
          <VariantPane
            variant="A"
            run={pair.a}
            result={result}
            stage={selectedStage}
            artifacts={artifacts.A ?? null}
            onOpenImage={(index) => setLightbox({ variant: "A", index })}
          />
          <VariantPane
            variant="B"
            run={pair.b}
            result={result}
            stage={selectedStage}
            artifacts={artifacts.B ?? null}
            onOpenImage={(index) => setLightbox({ variant: "B", index })}
          />
        </section>
      </main>

      {lightbox && activeImages.length > 0 && (
        <ImageLightbox
          images={activeImages.map((img) => ({
            src: fileUrl(img.image_path),
            alt: `씬 ${img.scene_num} · ${img.shot_id}`,
          }))}
          index={lightbox.index}
          onIndexChange={(index) => setLightbox({ ...lightbox, index })}
          onClose={() => setLightbox(null)}
        />
      )}
    </RouteShell>
  )
}

function RouteShell({ run, children }: { run: Run; children: ReactNode }) {
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
        <button
          type="button"
          onClick={() => navigate(`/runs/${run.id}`)}
          className="font-mono text-[12px] font-bold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {run.scp_id}
        </button>
        <StatusBadge status={run.status} />
      </nav>
      {children}
    </div>
  )
}

function VariantPane({
  variant,
  run,
  result,
  stage,
  artifacts,
  onOpenImage,
}: {
  variant: AbVariant
  run: Run
  result: AbResult | null
  stage: StageName
  artifacts: StageArtifacts | null
  onOpenImage: (index: number) => void
}) {
  return (
    <section aria-label={`Variant ${variant}`} className="min-w-0 border-l border-border pl-4">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[16px] font-semibold text-foreground">Variant {variant}</h2>
          <p className="mt-1 font-mono text-[11px] text-subtle-foreground">{run.id}</p>
        </div>
        <StatusBadge status={run.status} />
      </div>

      <ScoreTable title="LLM-as-judge" rows={LLM_AXES} scores={result?.llm_scores?.[variant]} />
      <ScoreTable title="rule-based" rows={RULE_METRICS} scores={result?.rule_scores?.[variant]} />

      <div className="mt-5 border-t border-border pt-4">
        <ArtifactPanel
          runId={run.id}
          stage={stage}
          data={artifacts}
          gateState="n/a"
          onOpenImage={onOpenImage}
          onGateStateChange={() => {}}
          onRetryStart={() => {}}
        />
      </div>
    </section>
  )
}

function ScoreTable({
  title,
  rows,
  scores,
}: {
  title: string
  rows: readonly string[]
  scores?: Partial<Record<string, number>>
}) {
  return (
    <div className="mb-3">
      <h3 className="mb-1 text-[12px] font-semibold text-muted-foreground">{title}</h3>
      <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-[12px]">
        {rows.map((row) => (
          <div key={row} className="contents">
            <dt className="font-mono text-subtle-foreground">{row}</dt>
            <dd className="text-foreground">{formatScore(scores?.[row])}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function WinnerSummary({ result }: { result: AbResult }) {
  if (result.winner === "tie") {
    return <ResultPill label="동점" reason={result.reason} />
  }
  if (result.winner === null) {
    return <ResultPill label="승자 없음" reason={result.reason} />
  }
  return <ResultPill label={`승자: Variant ${result.winner}`} reason={result.reason} />
}

function ResultPill({ label, reason }: { label: string; reason?: string }) {
  return (
    <div role="status" className="ml-auto rounded-md bg-status-approved-bg px-3 py-2 text-[12px] text-status-approved">
      <span className="font-semibold">{label}</span>
      {reason && <span className="ml-2 text-muted-foreground">{reason}</span>}
    </div>
  )
}

function StateMessage({ kind, message }: { kind: "status" | "alert"; message: string }) {
  return (
    <p
      role={kind}
      className={cn(
        "ml-auto rounded-md px-3 py-2 text-[12px]",
        kind === "alert" ? "bg-status-failed-bg text-status-failed" : "bg-status-awaiting-bg text-status-awaiting",
      )}
    >
      {message}
    </p>
  )
}

function getNonSuccessState(a: Run, b: Run, result: AbResult | null): { kind: "status" | "alert"; message: string } | null {
  if (a.status === "failed") return { kind: "alert", message: "Variant A 실패" }
  if (b.status === "failed") return { kind: "alert", message: "Variant B 실패" }
  if (a.status !== "complete") return { kind: "status", message: "Variant A 실행 중" }
  if (b.status !== "complete") return { kind: "status", message: "Variant B 실행 중" }
  if (!result) return { kind: "status", message: "평가 대기" }
  return null
}

function formatScore(value: number | undefined): string {
  if (value == null) return "결과 없음"
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

function getImages(data: StageArtifacts | null | undefined): ImageArtifacts["images"] {
  return data?.stage === "image" ? data.images : []
}
