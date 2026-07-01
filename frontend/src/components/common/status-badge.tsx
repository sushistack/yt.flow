import { cn } from "@/lib/utils"
import type { GateState, RunStatus } from "@/lib/types"

// Tone tokens are an independent semantic tier (DESIGN.md). Class strings are
// written in full because Tailwind v4 only emits utilities it finds literally.
type Tone = "running" | "awaiting" | "approved" | "failed" | "muted"

const TONE_CLASS: Record<Tone, string> = {
  running: "text-status-running bg-status-running-bg",
  awaiting: "text-status-awaiting bg-status-awaiting-bg",
  approved: "text-status-approved bg-status-approved-bg",
  failed: "text-status-failed bg-status-failed-bg",
  muted: "text-muted-foreground bg-card",
}

// Operator-facing status strings are Korean; the label text is what makes the
// state readable without relying on color (accessibility floor, UX-DR17).
const STATUS_META: Record<RunStatus | GateState, { tone: Tone; label: string }> = {
  running: { tone: "running", label: "실행 중" },
  awaiting_approval: { tone: "awaiting", label: "승인 대기" },
  complete: { tone: "approved", label: "완료" },
  failed: { tone: "failed", label: "실패" },
  pending: { tone: "awaiting", label: "대기" },
  approved: { tone: "approved", label: "승인됨" },
  rejected: { tone: "failed", label: "거부됨" },
  "n/a": { tone: "muted", label: "해당 없음" },
}

export type StatusBadgeProps = {
  status: RunStatus | GateState
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const { tone, label } = STATUS_META[status]
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-badge px-2 py-[3px] text-[11px] font-medium",
        TONE_CLASS[tone],
        className,
      )}
    >
      {label}
    </span>
  )
}
