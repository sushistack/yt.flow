import { useState } from "react"
import { ApiError, fileUrl, finalizeCharacter, generateCandidates } from "@/lib/api"
import type { CharacterCandidate } from "@/lib/types"

type Props = {
  charId: string
  candidates: CharacterCandidate[]
  onCandidatesRefresh: () => void
  hasReferences: boolean
}

const ANGLE_ORDER = ["front", "back", "side", "three_quarter"] as const
const ANGLE_LABELS: Record<string, string> = {
  front: "전면",
  back: "후면",
  side: "측면",
  three_quarter: "3/4",
}

export function CandidatePanel({ charId, candidates, onCandidatesRefresh, hasReferences }: Props) {
  const [generating, setGenerating] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleGenerate = async () => {
    setGenerating(true)
    setError(null)
    try {
      await generateCandidates(charId)
      // Start polling immediately via the parent's refresh
      onCandidatesRefresh()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "생성 시작에 실패했습니다.")
    } finally {
      setGenerating(false)
    }
  }

  const handleFinalize = async () => {
    setFinalizing(true)
    setError(null)
    try {
      await finalizeCharacter(charId)
      onCandidatesRefresh()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "확정에 실패했습니다.")
    } finally {
      setFinalizing(false)
    }
  }

  // Map candidates by angle for the 2x2 grid
  const byAngle = new Map<string, CharacterCandidate>()
  for (const c of candidates) {
    byAngle.set(c.angle, c)
  }

  const allReady = ANGLE_ORDER.every((a) => byAngle.get(a)?.status === "ready")
  const hasAny = candidates.length > 0

  return (
    <section className="mb-6 rounded-lg border border-border bg-card p-4" aria-label="후보 생성">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[13px] font-semibold text-muted-foreground">후보 생성</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating || !hasReferences}
            className="rounded-cta bg-primary px-4 py-1.5 text-[12px] font-semibold text-primary-foreground disabled:opacity-50 transition-opacity"
            title={!hasReferences ? "참조 이미지를 먼저 검색하세요" : undefined}
          >
            {generating ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                생성 중…
              </span>
            ) : (
              "후보 생성"
            )}
          </button>
          {hasAny && (
            <button
              type="button"
              onClick={handleFinalize}
              disabled={!allReady || finalizing}
              className="rounded-cta border border-primary/30 bg-primary/10 px-4 py-1.5 text-[12px] font-semibold text-primary disabled:opacity-30 transition-opacity"
            >
              {finalizing ? "확정 중…" : "캐릭터 확정"}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-3 rounded bg-status-failed-bg px-3 py-2 text-[12px] text-status-failed">
          {error}
        </div>
      )}

      {!hasAny ? (
        <p className="text-[13px] text-muted-foreground py-4 text-center">
          {hasReferences
            ? '"후보 생성"을 눌러 4개 각도의 캐릭터 이미지를 생성합니다.'
            : '참조 이미지를 먼저 검색해야 후보 생성이 가능합니다.'}
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-3" role="group" aria-label="각도별 생성 상태">
          {ANGLE_ORDER.map((angle) => {
            const candidate = byAngle.get(angle)
            return (
              <div
                key={angle}
                className="overflow-hidden rounded-lg border border-border"
                role="status"
                aria-label={`${ANGLE_LABELS[angle]} — ${statusLabel(candidate?.status)}`}
              >
                {candidate?.status === "ready" && candidate.image_path ? (
                  <img
                    src={fileUrl(candidate.image_path)}
                    alt={`${ANGLE_LABELS[angle]} 후보`}
                    className="aspect-square w-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="flex aspect-square items-center justify-center bg-card-hover">
                    {candidate?.status === "generating" || candidate?.status === "pending" ? (
                      <span className="flex flex-col items-center gap-1.5 text-[12px] text-muted-foreground">
                        <span className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                        생성 중…
                      </span>
                    ) : candidate?.status === "failed" ? (
                      <span className="flex flex-col items-center gap-1.5 text-[12px] text-status-failed">
                        <span className="text-[20px]">⚠</span>
                        실패
                      </span>
                    ) : (
                      <span className="text-[12px] text-muted-foreground">
                        대기 중
                      </span>
                    )}
                  </div>
                )}
                <div className="flex items-center justify-between px-3 py-1.5 border-t border-border">
                  <span className="text-[11px] font-medium text-muted-foreground">{ANGLE_LABELS[angle]}</span>
                  <StatusBadge status={candidate?.status} />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function statusLabel(status?: string): string {
  switch (status) {
    case "pending": return "대기 중"
    case "generating": return "생성 중"
    case "ready": return "완료"
    case "failed": return "실패"
    default: return "없음"
  }
}

function StatusBadge({ status }: { status?: string }) {
  let bg = "bg-white/10"
  let text = "text-muted-foreground"
  let label = "대기"
  let dot = "bg-muted-foreground"

  switch (status) {
    case "generating":
      bg = "bg-blue-500/10"
      text = "text-blue-400"
      label = "생성 중"
      dot = "bg-blue-400"
      break
    case "ready":
      bg = "bg-green-500/10"
      text = "text-green-400"
      label = "완료"
      dot = "bg-green-400"
      break
    case "failed":
      bg = "bg-red-500/10"
      text = "text-red-400"
      label = "실패"
      dot = "bg-red-400"
      break
  }

  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${bg} ${text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      {label}
    </span>
  )
}
