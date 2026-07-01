import { useEffect, useRef, useState } from "react"
import {
  ApiError,
  approveGate,
  fileUrl,
  patchStageArtifact,
  rejectGate,
  retryStage,
  videoDownloadUrl,
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

  return (
    <section className="flex min-h-full flex-col gap-4" aria-label={`${stage} artifact`}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <h1 className="font-mono text-[13px] font-semibold text-foreground">{stage}</h1>
          {gateState !== "n/a" && <StatusBadge status={gateState} />}
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

      {gateState === "pending" && (
        <GateControls runId={runId} stage={stage} onGateStateChange={onGateStateChange} />
      )}
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
  const cueCount = (text.match(/-->/g) ?? []).length
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
