import { useEffect, useState } from "react"
import { fileUrl, videoDownloadUrl, type StageArtifacts } from "@/lib/api"

const NOT_REACHED = "아직 실행되지 않은 스테이지입니다."

type Props = {
  runId: string
  data: StageArtifacts | null | undefined
  onOpenImage: (index: number) => void
}

// One panel per stage, chosen by the artifact DTO's own discriminant.
// `undefined` is a reachable stage loading state; `null` is the API's 404/not-reached state.
export function ArtifactPanel({ runId, data, onOpenImage }: Props) {
  if (data === undefined) return <LoadingState />
  if (data === null) return <EmptyState />
  switch (data.stage) {
    case "scenario":
      return <ScenarioPanel scenes={data.scenes} />
    case "image":
      return <ImagePanel images={data.images} onOpenImage={onOpenImage} />
    case "tts":
      return <TtsPanel audio={data.audio} />
    case "subtitle":
      return <SubtitlePanel subtitles={data.subtitles} />
    case "video":
      return <VideoPanel runId={runId} videoPath={data.video_path} />
    default:
      return <EmptyState />
  }
}

function EmptyState() {
  return <p className="text-muted-foreground">{NOT_REACHED}</p>
}

function LoadingState() {
  return <p className="text-muted-foreground">불러오는 중...</p>
}

export function sortImagesByScene<T extends { scene_num: number; shot_id: string }>(images: T[]): T[] {
  return [...images].sort(
    (a, b) => a.scene_num - b.scene_num || a.shot_id.localeCompare(b.shot_id),
  )
}

function ScenarioPanel({ scenes }: { scenes: { scene_num: number; narration: string }[] }) {
  const prose = scenes.map((s) => s.narration).join("\n\n")
  return (
    // ~65ch measure + 1.6 line-height for long-form Korean reading (AC2).
    <div
      className="overflow-auto whitespace-pre-wrap leading-[1.6] text-foreground"
      style={{ maxWidth: "65ch" }}
    >
      {prose}
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
  const sorted = sortImagesByScene(images)
  return (
    <div>
      <p className="mb-3 text-muted-foreground">이미지 {images.length}개</p>
      <div className="grid grid-cols-2 gap-3">
        {sorted.map((img, i) => (
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

function SubtitlePanel({ subtitles }: { subtitles: { scene_num: number; subtitle_path: string }[] }) {
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
      <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-card p-4 font-mono text-[12px] text-foreground">
        {text}
      </pre>
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
