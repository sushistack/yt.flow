import { useEffect, useRef, useState } from "react"
import {
  ApiError,
  approveGate,
  fileUrl,
  patchStageArtifact,
  rejectGate,
  retryStage,
  videoDownloadUrl,
  type RunWarning,
  type ScenarioQuality,
  type StageArtifacts,
} from "@/lib/api"
import type { GateState, StageName } from "@/lib/types"
import { StatusBadge } from "@/components/common"
import { cn } from "@/lib/utils"

const NOT_REACHED = "아직 실행되지 않은 스테이지입니다."
const EDITABLE_STAGES = new Set<StageName>(["scenario", "subtitle"])

type Props = {
  runId: string
  stage: StageName
  data: StageArtifacts | null
  gateState: GateState
  onOpenImage: (index: number) => void
  onGateStateChange: (stage: StageName, gateState: GateState) => void
  onRetryStart: (stage: StageName) => void
  onDirtyChange?: (dirty: boolean) => void
}

// One panel per stage, chosen by the artifact DTO's own discriminant.
// `data === null` means the stage has no artifacts yet (not reached, or the
// artifacts endpoint 404'd) → muted empty state (AC8).
export function ArtifactPanel({
  runId,
  stage,
  data,
  gateState,
  onOpenImage,
  onGateStateChange,
  onRetryStart,
  onDirtyChange,
}: Props) {
  const [confirmRetry, setConfirmRetry] = useState(false)
  const [retryError, setRetryError] = useState<string | null>(null)

  useEffect(() => {
    setConfirmRetry(false)
    setRetryError(null)
  }, [stage])

  useEffect(() => {
    if (!confirmRetry) return
    const id = window.setTimeout(() => setConfirmRetry(false), 5000)
    return () => window.clearTimeout(id)
  }, [confirmRetry, stage])

  async function handleRetry() {
    setRetryError(null)
    try {
      await retryStage(runId, stage)
      setConfirmRetry(false)
      onRetryStart(stage)
    } catch (error) {
      setRetryError(error instanceof ApiError ? error.message : "재시도 요청에 실패했습니다")
    }
  }

  const canRetry = gateState === "approved" || gateState === "rejected" || gateState === "failed"
  // Story 13.1: one field, every stage — the DTO carries the whole run's degradation
  // history and each record names the stage it belongs to. `?? []` covers a legacy
  // checkpoint's response, which has no `warnings` key at all.
  const warnings = data?.warnings ?? []

  return (
    <section className="flex min-h-full flex-col gap-4" aria-label={`${stage} artifact`}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <h1 className="font-mono text-[13px] font-semibold text-foreground">{stage}</h1>
          {gateState !== "n/a" && <StatusBadge status={gateState} />}
          {warnings.length > 0 && (
            <span className="rounded-sm border border-border bg-card px-2 py-0.5 text-[11px] text-foreground">
              <span aria-hidden="true">⚠</span> 경고 {warnings.length}건
            </span>
          )}
        </div>
        {canRetry && (
          <div className="flex flex-col items-end gap-2">
            <button
              type="button"
              onClick={() => setConfirmRetry(true)}
              className="rounded-sm border border-border px-3 py-1.5 text-[12px] text-foreground hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              재시도
            </button>
            {confirmRetry && (
              <div role="alert" className="rounded-sm border border-border bg-card p-3 text-[12px] text-foreground">
                <p className="mb-2">이 스테이지를 다시 실행합니까?</p>
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={handleRetry}
                    className="rounded-sm bg-primary px-3 py-1 text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    확인
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmRetry(false)}
                    className="rounded-sm border border-border px-3 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    취소
                  </button>
                </div>
              </div>
            )}
            {retryError && <p className="text-[12px] text-status-failed">{retryError}</p>}
          </div>
        )}
      </header>

      <div className="flex-1">
        <PanelBody runId={runId} stage={stage} data={data} onOpenImage={onOpenImage} onDirtyChange={onDirtyChange} />
      </div>

      {/* Both contracts render when both are present: 12.3's block is the scenario
          review verdict, this one is the run's fallback history. Neither replaces
          the other, and neither is a gate state. */}
      {data?.stage === "scenario" && data.scenario_quality?.warning && (
        <ScenarioQualityWarning quality={data.scenario_quality} />
      )}

      {warnings.length > 0 && <RunWarningList warnings={warnings} />}

      {gateState === "pending" && (
        <GateControls runId={runId} stage={stage} onGateStateChange={onGateStateChange} />
      )}
    </section>
  )
}

// Story 13.1: the run's non-fatal degradations, rendered above the gate controls for
// the same reason 12.3's block is — approving a fallback result has to be a knowing act.
// Deliberately neutral: `border-border`/`bg-card`/`text-foreground` plus icon + count,
// never a status colour. `status-awaiting` and friends mean gate STATE, and a warning is
// not a gate state; a run can be fully approved and still carry ten of these.
function RunWarningList({ warnings }: { warnings: RunWarning[] }) {
  // A labelled region, NOT an alert: `role="alert"` implies assertive (and contradicts
  // `aria-live="polite"`), and this block is statically rendered with the panel rather
  // than inserted in response to anything — announcing it would re-read the whole run
  // history on every stage switch, over the header badge that already says "경고 N건".
  return (
    <section
      aria-labelledby="run-warning-list-heading"
      className="rounded-md border border-border bg-card p-4 text-[12px] text-foreground"
    >
      <h2 id="run-warning-list-heading" className="mb-1 flex items-center gap-2 text-[13px] font-semibold">
        <span aria-hidden="true">⚠</span>
        경고 {warnings.length}건
      </h2>
      <p className="mb-3 text-subtle-foreground">
        실행 중 발생한 품질 저하 기록입니다. 실패가 아니며, 재시도할 때마다 다시 일어나지는 않습니다.
      </p>
      <ul className="flex flex-col gap-2">
        {warnings.map((warning, i) => {
          const where = identifierText(warning.context)
          return (
            <li key={`${warning.code}-${i}`} className="border-l-2 border-border pl-2">
              <span className="font-mono text-[11px] text-subtle-foreground">
                {warning.stage} · {warning.code}
                {where && ` · ${where}`}
              </span>
              <p className="leading-[1.6]">{warning.message}</p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

// The identifiers an operator can act on, in a fixed order so two runs read the same
// way. `detail` is excluded by construction — it is raw provider/exception text.
// `fallback_reason` is the single most valuable field the backend produces here: it is
// what finally distinguishes an angle fallback from an asset one from a missed pose hint.
const IDENTIFIER_LABELS: [string, (v: string | number | boolean) => string][] = [
  ["scene_num", (v) => `씬 ${v}`],
  ["shot_id", (v) => `${v}`],
  ["card_key", (v) => `${v}`],
  ["card_variant", (v) => `${v}`],
  ["location_key", (v) => `${v}`],
  ["pose_hint", (v) => `요청 포즈 ${v}`],
  ["pose", (v) => `포즈 ${v}`],
  ["angle", (v) => `앵글 ${v}`],
  ["fallback_reason", (v) => `대체 ${v}`],
  ["reason", (v) => `${v}`],
  ["cap", (v) => `한도 ${v}`],
  ["attempts", (v) => `시도 ${v}`],
  ["failed_count", (v) => `실패 ${v}건`],
  ["skipped_count", (v) => `생략 ${v}건`],
  ["total_count", (v) => `총 ${v}건`],
]

function identifierText(context: RunWarning["context"]): string {
  if (!context) return ""
  return IDENTIFIER_LABELS.filter(([key]) => context[key] !== undefined)
    .map(([key, format]) => format(context[key]))
    .join(" · ")
}

// Story 12.3: the scenario script is still degraded after its one allowed repair
// pass. Rendered directly above the approve/reject controls — the operator has to
// see it to make the decision, which is why this is not a toast and not a
// separate page. Signalled by icon + heading text as well as colour.
function ScenarioQualityWarning({ quality }: { quality: ScenarioQuality }) {
  const {
    rule_metrics: metrics,
    grounded_contradictions: contradictions,
    review_issues: issues,
    critic_scene_notes: criticNotes = [],
  } = quality
  return (
    <section
      role="alert"
      aria-live="polite"
      className="rounded-md border border-status-awaiting bg-card p-4 text-[12px] text-foreground"
    >
      <h2 className="mb-1 flex items-center gap-2 text-[13px] font-semibold">
        <span aria-hidden="true">⚠</span>
        2차 검토 경고
      </h2>
      <p className="mb-2 leading-[1.6]">{quality.warning?.message}</p>
      {/* Story 12.6: a fabricated-fact finding and a pacing complaint used to reach
          this gate as the same undifferentiated warning. Its own line, not folded
          into the message, because the two call for different operator actions. */}
      {quality.warning?.categories?.length ? (
        <p className="mb-2 font-mono text-[11px] text-subtle-foreground">
          유형: {quality.warning.categories.join(" · ")}
        </p>
      ) : null}
      {/* AC8: an inline narration edit does not re-run review, so the evidence stays
          on screen and is labelled as of its generation time rather than silently
          re-read as a verdict on the edited text. */}
      <p className="mb-3 text-subtle-foreground">
        대본 생성 시점의 자동 검토 결과입니다. 이후 직접 수정한 내용은 재검토되지 않았습니다.
      </p>

      <p className="mb-3 font-mono text-[11px] text-subtle-foreground">
        pass {quality.final_pass_index} · retry_scope {quality.retry_scope} · critic{" "}
        {quality.critic_verdict} · review {quality.review_overall_pass ? "pass" : "fail"}
      </p>

      {quality.critic_feedback && (
        <div className="mb-3">
          <h3 className="mb-1 font-semibold">비평 요약</h3>
          <p className="whitespace-pre-wrap leading-[1.6]" style={{ maxWidth: "65ch" }}>
            {quality.critic_feedback}
          </p>
        </div>
      )}

      {contradictions.length > 0 && (
        <div className="mb-3">
          <h3 className="mb-1 font-semibold">접지 모순 {contradictions.length}건</h3>
          <ul className="flex flex-col gap-2">
            {contradictions.map((c, i) => (
              <li key={`${c.scene_num}-${i}`} className="border-l-2 border-status-awaiting pl-2">
                <span className="font-mono text-[11px] text-subtle-foreground">씬 {c.scene_num}</span>
                <p className="leading-[1.6]">대본: “{c.narration_quote}”</p>
                <p className="leading-[1.6]">
                  <span className="font-mono text-[11px]">{c.grounding_source}</span>: “{c.grounding_quote}”
                </p>
                <p className="leading-[1.6] text-muted-foreground">{c.explanation}</p>
                <p className="leading-[1.6]">제안: {c.correction}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {issues.length > 0 && (
        <div className="mb-3">
          <h3 className="mb-1 font-semibold">미해결 지적 {issues.length}건</h3>
          <ul className="flex flex-col gap-1">
            {issues.map((issue, i) => (
              <li key={`${issue.scene_num}-${i}`} className="leading-[1.6]">
                <span className="font-mono text-[11px] text-subtle-foreground">
                  씬 {issue.scene_num} · {issue.type}
                </span>{" "}
                {issue.description}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Story 12.6: the critic's per-scene findings. Up to 20 of these ride every
          checkpoint, interrupt value and SSE frame — rendering them is what makes
          that payload worth carrying, and the `issue_type` leads each row because
          it is the field that says which of the two operator actions applies. */}
      {criticNotes.length > 0 && (
        <div className="mb-3">
          <h3 className="mb-1 font-semibold">비평 지적 {criticNotes.length}건</h3>
          <ul className="flex flex-col gap-1">
            {criticNotes.map((note, i) => (
              <li key={`${note.scene_num}-${i}`} className="leading-[1.6]">
                <span className="font-mono text-[11px] text-subtle-foreground">
                  씬 {note.scene_num} · {note.issue_type}
                </span>{" "}
                {note.issue}
                {note.suggestion && <span className="text-muted-foreground"> → {note.suggestion}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-1 font-semibold">기계 측정</h3>
        <p className="font-mono text-[11px] text-subtle-foreground">
          {metrics.aggregate.character_count}자 · {metrics.aggregate.sentence_count}문장 · 중복 문장{" "}
          {metrics.aggregate.duplicate_sentence_count} · 반복 4-그램{" "}
          {metrics.aggregate.repeated_4gram_count} · 상투구{" "}
          {metrics.slop_phrase_hits.reduce((n, h) => n + h.count, 0)}
        </p>
        {metrics.repeated_ngrams.length > 0 && (
          <p className="mt-1 leading-[1.6]">
            반복 표현: {metrics.repeated_ngrams.map((n) => `“${n.phrase}” ×${n.count}`).join(", ")}
          </p>
        )}
        {metrics.slop_phrase_hits.length > 0 && (
          <p className="mt-1 leading-[1.6]">
            상투구: {metrics.slop_phrase_hits.map((h) => `씬 ${h.scene_num} “${h.phrase}” ×${h.count}`).join(", ")}
          </p>
        )}
      </div>
    </section>
  )
}

function PanelBody({
  runId,
  stage,
  data,
  onOpenImage,
  onDirtyChange,
}: Pick<Props, "runId" | "stage" | "data" | "onOpenImage" | "onDirtyChange">) {
  if (data === null) return <EmptyState />
  switch (data.stage) {
    case "scenario":
      return <EditableTextPanel
        runId={runId}
        stage={stage}
        initialText={data.scenes.map((s) => s.narration).join("\n\n")}
        onDirtyChange={onDirtyChange}
      />
    case "image":
      return <ImagePanel images={data.images} onOpenImage={onOpenImage} />
    case "tts":
      return <TtsPanel audio={data.audio} />
    case "subtitle":
      return <SubtitlePanel runId={runId} stage={stage} subtitles={data.subtitles} onDirtyChange={onDirtyChange} />
    case "video":
      return <VideoPanel runId={runId} videoPath={data.video_path} />
    default:
      return <EmptyState />
  }
}

function EmptyState() {
  return <p className="text-muted-foreground">{NOT_REACHED}</p>
}

function EditableTextPanel({
  runId,
  stage,
  initialText,
  monospace = false,
  onDirtyChange,
}: {
  runId: string
  stage: StageName
  initialText: string
  monospace?: boolean
  onDirtyChange?: (dirty: boolean) => void
}) {
  const [savedText, setSavedText] = useState(initialText)
  const [draft, setDraft] = useState(initialText)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dirty = editing && draft !== savedText
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  useEffect(() => {
    setSavedText(initialText)
    setDraft(initialText)
    setEditing(false)
    setError(null)
    onDirtyChange?.(false)
  }, [initialText, stage, onDirtyChange])

  useEffect(() => {
    onDirtyChange?.(dirty)
  }, [dirty, onDirtyChange])

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const response = await patchStageArtifact(runId, stage, draft)
      if (!mountedRef.current) return
      const updated =
        response && "text" in response && typeof response.text === "string"
          ? response.text
          : response && "content" in response && typeof response.content === "string"
            ? response.content
            : draft
      setSavedText(updated)
      setDraft(updated)
      setEditing(false)
      onDirtyChange?.(false)
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.message : "저장에 실패했습니다")
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <div className="flex flex-col gap-3">
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className={cn(
            "min-h-[45vh] w-full resize-y rounded-sm border border-border bg-card p-3 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
            monospace ? "font-mono text-[12px]" : "leading-[1.6]",
          )}
        />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-sm bg-primary px-3 py-1.5 text-[12px] text-primary-foreground disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {saving && <Spinner />}
            저장
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(savedText)
              setEditing(false)
              setError(null)
              onDirtyChange?.(false)
            }}
            className="rounded-sm border border-border px-3 py-1.5 text-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            취소
          </button>
          {error && <p className="text-[12px] text-status-failed">{error}</p>}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {EDITABLE_STAGES.has(stage) && savedText && (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="self-start rounded-sm border border-border px-3 py-1.5 text-[12px] text-foreground hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          편집
        </button>
      )}
      {monospace ? (
        <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-card p-4 font-mono text-[12px] text-foreground">
          {savedText}
        </pre>
      ) : (
        <div
          className="overflow-auto whitespace-pre-wrap leading-[1.6] text-foreground"
          style={{ maxWidth: "65ch" }}
        >
          {savedText}
        </div>
      )}
    </div>
  )
}

function ImagePanel({
  images,
  onOpenImage,
}: {
  images: { scene_num: number; shot_id: string; image_path: string }[]
  onOpenImage: (index: number) => void
}) {
  return (
    <div>
      <p className="mb-3 text-muted-foreground">이미지 {images.length}개</p>
      <div className="grid grid-cols-2 gap-3">
        {images.map((img, i) => (
          <button
            key={`${img.scene_num}-${img.shot_id}`}
            type="button"
            onClick={() => onOpenImage(i)}
            className="group text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <div className="aspect-video overflow-hidden rounded-md border border-border bg-card">
              <img
                src={fileUrl(img.image_path)}
                alt={`씬 ${img.scene_num} · ${img.shot_id}`}
                loading="lazy"
                className="h-full w-full object-cover transition-transform group-hover:scale-[1.02]"
              />
            </div>
            <span className="mt-1 block font-mono text-[11px] text-subtle-foreground">
              씬 {img.scene_num} · {img.shot_id}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

function TtsPanel({ audio }: { audio: { scene_num: number; audio_path: string; duration_sec: number | null }[] }) {
  const sorted = [...audio].sort((a, b) => a.scene_num - b.scene_num)
  return (
    <ul className="flex flex-col gap-4">
      {sorted.map((a) => (
        <li key={a.scene_num} className="flex flex-col gap-1">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[11px] text-subtle-foreground">씬 {a.scene_num}</span>
            {a.duration_sec != null && (
              <span className="text-[11px] text-muted-foreground">{a.duration_sec.toFixed(1)}초</span>
            )}
          </div>
          <audio controls src={fileUrl(a.audio_path)} className="w-full" />
        </li>
      ))}
    </ul>
  )
}

function SubtitlePanel({
  runId,
  stage,
  subtitles,
  onDirtyChange,
}: {
  runId: string
  stage: StageName
  subtitles: { scene_num: number; subtitle_path: string }[]
  onDirtyChange?: (dirty: boolean) => void
}) {
  const [text, setText] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const sorted = [...subtitles].sort((a, b) => a.scene_num - b.scene_num)
    Promise.all(
      sorted.map((s) =>
        fetch(fileUrl(s.subtitle_path))
          .then((r) => (r.ok ? r.text() : ""))
          .catch(() => ""),
      ),
    ).then((chunks) => {
      if (alive) setText(chunks.join("\n\n"))
    })
    return () => {
      alive = false
    }
  }, [subtitles])

  if (text === null) return <p className="text-muted-foreground">불러오는 중…</p>
  // Per-line OR, not two summed regexes: a Dialogue event's own text can contain
  // a literal "-->" (e.g. narration with an arrow), which would double-count it.
  const cueCount = text.split("\n").filter((l) => l.startsWith("Dialogue:") || l.includes("-->")).length
  return (
    <div>
      <p className="mb-3 text-muted-foreground">자막 {cueCount}개</p>
      <EditableTextPanel runId={runId} stage={stage} initialText={text} monospace onDirtyChange={onDirtyChange} />
    </div>
  )
}

function VideoPanel({ runId, videoPath }: { runId: string; videoPath: string }) {
  return (
    <div className="flex flex-col gap-3">
      <video controls src={fileUrl(videoPath)} className="w-full rounded-md border border-border bg-black" />
      <a
        href={videoDownloadUrl(runId)}
        download
        className="text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        영상 다운로드
      </a>
    </div>
  )
}

function GateControls({
  runId,
  stage,
  onGateStateChange,
}: {
  runId: string
  stage: StageName
  onGateStateChange: (stage: StageName, gateState: GateState) => void
}) {
  const [pendingAction, setPendingAction] = useState<"approve" | "reject" | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(action: "approve" | "reject") {
    setPendingAction(action)
    setError(null)
    try {
      if (action === "approve") {
        await approveGate(runId, stage)
        onGateStateChange(stage, "approved")
      } else {
        await rejectGate(runId, stage)
        onGateStateChange(stage, "rejected")
      }
    } catch (gateError) {
      setError(gateError instanceof ApiError ? gateError.message : "게이트 요청에 실패했습니다")
    } finally {
      setPendingAction(null)
    }
  }

  return (
    <footer className="border-t border-border pt-4">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => submit("approve")}
          disabled={pendingAction !== null}
          className="inline-flex items-center gap-2 rounded-sm bg-primary px-3 py-1.5 text-[12px] font-medium text-primary-foreground disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {pendingAction && <Spinner />}
          승인
        </button>
        <button
          type="button"
          onClick={() => submit("reject")}
          disabled={pendingAction !== null}
          className="inline-flex items-center gap-2 rounded-sm border border-status-failed px-3 py-1.5 text-[12px] font-medium text-status-failed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-status-failed"
        >
          {pendingAction && <Spinner />}
          반려
        </button>
      </div>
      {error && <p className="mt-2 text-[12px] text-status-failed">{error}</p>}
    </footer>
  )
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  )
}
