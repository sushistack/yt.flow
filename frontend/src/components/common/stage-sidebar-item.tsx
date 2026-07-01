import { cn } from "@/lib/utils"
import type { GateState, StageName } from "@/lib/types"

// Gate signals carry a glyph + Korean label so state never rides on color alone
// (accessibility floor, UX-DR17). n/a shows nothing.
const GATE_META: Record<GateState, { glyph: string; label: string; className: string } | null> = {
  pending: { glyph: "⏸", label: "승인 대기", className: "text-status-awaiting" },
  approved: { glyph: "✓", label: "승인됨", className: "text-status-approved" },
  rejected: { glyph: "✗", label: "거부됨", className: "text-status-failed" },
  "n/a": null,
}

export type StageSidebarItemProps = {
  stage: StageName
  active?: boolean
  gateState?: GateState
  reached?: boolean
  onSelect?: (stage: StageName) => void
  className?: string
}

export function StageSidebarItem({
  stage,
  active = false,
  gateState = "n/a",
  reached = true,
  onSelect,
  className,
}: StageSidebarItemProps) {
  const gate = GATE_META[gateState]
  const borderClass = active
    ? "border-l-primary"
    : gateState === "pending"
      ? "border-l-status-awaiting"
      : "border-l-transparent"

  const base = cn(
    "flex w-full items-center gap-2 border-l-2 px-3 py-2 text-left",
    borderClass,
    active ? "bg-card text-foreground" : "text-muted-foreground",
    !reached && "opacity-50",
    className,
  )

  const content = (
    <>
      {/* Stage token: mono 11px, subtle-foreground per DESIGN.md Components;
          the active row keeps its stronger foreground for the current-stage cue. */}
      <span className={cn("font-mono text-[11px]", !active && "text-subtle-foreground")}>{stage}</span>
      {gate && (
        <span className={cn("ml-auto inline-flex items-center gap-1 text-[11px]", gate.className)}>
          <span aria-hidden="true">{gate.glyph}</span>
          {gate.label}
        </span>
      )}
    </>
  )

  // Unreached stages are muted and cannot trigger navigation (AC5).
  if (!reached) {
    return (
      <div aria-disabled="true" className={cn(base, "cursor-not-allowed")}>
        {content}
      </div>
    )
  }

  if (onSelect) {
    return (
      <button
        type="button"
        aria-current={active ? "true" : undefined}
        onClick={() => onSelect(stage)}
        className={cn(base, "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary")}
      >
        {content}
      </button>
    )
  }

  return (
    <div aria-current={active ? "true" : undefined} className={base}>
      {content}
    </div>
  )
}
