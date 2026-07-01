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
// The glyph is a decorative prefix per EXPERIENCE.md state tables (●/⏸/✓/✗)
// and is aria-hidden so assistive tech reads only the label.
type Meta = { tone: Tone; glyph: string; label: string }

const STATUS_META: Record<RunStatus | GateState, Meta> = {
  running: { tone: "running", glyph: "●", label: "실행 중" },
  awaiting_approval: { tone: "awaiting", glyph: "⏸", label: "승인 대기" },
  complete: { tone: "approved", glyph: "✓", label: "완료" },
  failed: { tone: "failed", glyph: "✗", label: "실패" },
  pending: { tone: "awaiting", glyph: "⏸", label: "승인 대기" },
  approved: { tone: "approved", glyph: "✓", label: "승인됨" },
  rejected: { tone: "failed", glyph: "✗", label: "거부됨" },
  "n/a": { tone: "muted", glyph: "", label: "해당 없음" },
}

export type StatusBadgeProps = {
  status: RunStatus | GateState
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  // status comes from the API contract (a trust boundary); an out-of-union
  // value degrades to a muted badge showing the raw string instead of crashing.
  const { tone, glyph, label } = STATUS_META[status] ?? {
    tone: "muted",
    glyph: "",
    label: String(status),
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-badge px-2 py-[3px] text-[11px] font-medium",
        TONE_CLASS[tone],
        className,
      )}
    >
      {glyph && <span aria-hidden="true">{glyph}</span>}
      {label}
    </span>
  )
}
