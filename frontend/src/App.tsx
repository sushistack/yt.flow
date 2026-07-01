// Foundation smoke screen only: exercises Zinc tokens, sans body, and the mono
// stack. Real UI (Dashboard, SCP Picker, Run Detail, gates, SSE, A/B) lands in
// stories 3.2–3.6. ponytail: intentionally minimal — visual/build smoke target.

const STATUSES = [
  { key: "running", label: "실행 중" },
  { key: "awaiting", label: "대기 중" },
  { key: "approved", label: "승인됨" },
  { key: "failed", label: "실패" },
] as const

const STAGES = ["scenario", "image", "tts", "subtitle", "video"]

function StatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <span
      className="rounded-badge px-2 py-[3px] text-[11px] font-medium"
      style={{
        color: `var(--status-${status})`,
        backgroundColor: `var(--status-${status}-bg)`,
      }}
    >
      {label}
    </span>
  )
}

export default function App() {
  return (
    <main className="mx-auto max-w-3xl p-8">
      <header className="mb-6 flex items-baseline gap-3">
        <span className="text-[15px] font-semibold text-foreground">yt.flow</span>
        <span className="text-[11px] text-muted-foreground">파이프라인 제어 워크벤치</span>
      </header>

      <section className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center gap-3">
          <span className="font-mono text-[12px] font-bold text-foreground">SCP-096</span>
          <span className="text-foreground">부끄러운 남자</span>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {STATUSES.map((s) => (
            <StatusBadge key={s.key} status={s.key} label={s.label} />
          ))}
        </div>

        <div className="mt-4 flex flex-wrap gap-3">
          {STAGES.map((stage) => (
            <span key={stage} className="font-mono text-[11px] text-subtle-foreground">
              {stage}
            </span>
          ))}
        </div>

        <button className="mt-6 rounded-cta bg-primary px-4 py-2 text-[13px] font-medium text-primary-foreground">
          새 실행 시작
        </button>
      </section>
    </main>
  )
}
