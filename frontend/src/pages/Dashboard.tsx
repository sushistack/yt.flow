import { useEffect, useState } from "react"
import { ApiError, getRuns } from "@/lib/api"
import { navigate } from "@/lib/navigate"
import { sortRuns } from "@/lib/runSorting"
import type { Run } from "@/lib/types"
import { RunRow } from "@/components/RunRow"
import { SCPPickerDialog } from "@/components/SCPPickerDialog"

const API_DOWN = "서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요."

function TopNav({ onNewRun }: { onNewRun: () => void }) {
  return (
    <nav className="flex h-[52px] items-center border-b border-border px-6">
      <span className="text-[15px] font-semibold tracking-tight text-foreground">
        yt<span className="text-primary">.</span>flow
      </span>
      <button
        type="button"
        onClick={onNewRun}
        className="ml-auto rounded-cta bg-primary px-[15px] py-[7px] text-[13px] font-semibold text-primary-foreground"
      >
        + 새 실행
      </button>
    </nav>
  )
}

export function Dashboard() {
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [apiDown, setApiDown] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)

  const load = () =>
    getRuns()
      .then((data) => {
        setRuns(data)
        setApiDown(false)
      })
      .catch((e) => {
        if (e instanceof ApiError) setApiDown(true)
        setRuns([])
      })

  useEffect(() => {
    void load()
  }, [])

  const onCreated = (run: Run) => {
    // Optimistic insert at the top, then refetch so server ordering wins (AC6).
    setRuns((prev) => [run, ...(prev ?? [])])
    void load()
  }

  return (
    <div className="min-h-screen bg-background">
      <TopNav onNewRun={() => setDialogOpen(true)} />

      {apiDown && (
        <div role="alert" className="bg-status-failed-bg px-6 py-2.5 text-[12px] text-status-failed">
          {API_DOWN}
        </div>
      )}

      <main className="p-6">
        <div className="mb-2.5 text-[13px] font-semibold text-muted-foreground">실행 목록</div>

        {runs === null ? (
          <div className="overflow-hidden rounded-lg bg-card" aria-hidden="true">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3.5 border-b border-border px-4 py-3.5">
                <div className="h-4 w-[92px] animate-pulse rounded bg-white/10" />
                <div className="h-5 w-24 animate-pulse rounded bg-white/10" />
                <div className="ml-auto h-4 w-16 animate-pulse rounded bg-white/10" />
              </div>
            ))}
          </div>
        ) : runs.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-20 text-center">
            <p className="text-[13px] text-muted-foreground">실행 없음. 새 실행을 시작하세요.</p>
            <button
              type="button"
              onClick={() => setDialogOpen(true)}
              className="rounded-cta bg-primary px-4 py-2 text-[13px] font-semibold text-primary-foreground"
            >
              + 새 실행
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg bg-card">
            {sortRuns(runs).map((run) => (
              <RunRow key={run.id} run={run} onOpen={(id) => navigate(`/runs/${id}`)} />
            ))}
          </div>
        )}
      </main>

      <SCPPickerDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onCreated={onCreated}
      />
    </div>
  )
}
