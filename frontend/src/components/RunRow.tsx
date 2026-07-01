import { CardRow, StatusBadge } from "@/components/common"
import type { Run } from "@/lib/types"

// Relative Korean time; ISO string → "방금 전 / N분 전 / N시간 전 / N일 전".
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const min = Math.floor(diff / 60000)
  if (min < 1) return "방금 전"
  if (min < 60) return `${min}분 전`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}시간 전`
  return `${Math.floor(hr / 24)}일 전`
}

export function RunRow({ run, onOpen }: { run: Run; onOpen: (id: string) => void }) {
  return (
    <CardRow
      onClick={() => onOpen(run.id)}
      // Awaiting rows get a left accent strip (mockup .run-row-wait).
      className={run.status === "awaiting_approval" ? "border-l-2 border-l-status-awaiting" : undefined}
    >
      <div className="flex items-center gap-3.5">
        <span className="min-w-[92px] font-mono text-[12px] font-bold text-foreground">
          {run.scp_id}
        </span>
        <div className="flex flex-1 flex-col items-start gap-1">
          <StatusBadge status={run.status} />
          <span className="font-mono text-[11px] text-subtle-foreground">
            {run.current_stage ?? (run.status === "complete" ? "complete" : "—")}
          </span>
        </div>
        <span className="whitespace-nowrap text-[12px] tabular-nums text-subtle-foreground">
          {timeAgo(run.started_at)}
        </span>
        <span aria-hidden="true" className="text-[15px] text-subtle-foreground">
          ›
        </span>
      </div>
    </CardRow>
  )
}
