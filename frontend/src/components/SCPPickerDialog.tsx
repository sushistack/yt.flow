import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { ApiError, createRun, getScps } from "@/lib/api"
import { filterScps, sortScpsByRating } from "@/lib/scpSearch"
import type { Run, ScpEntry } from "@/lib/types"

const ROW_HEIGHT = 52 // px; matches .picker-row density in the mockup

type Props = {
  open: boolean
  onClose: () => void
  onCreated: (run: Run) => void
}

export function SCPPickerDialog({ open, onClose, onCreated }: Props) {
  const [scps, setScps] = useState<ScpEntry[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [debounced, setDebounced] = useState("")
  const [active, setActive] = useState(0)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Fetch once on first open; cache for later opens (shared client cache, UX-DR8).
  useEffect(() => {
    if (!open || scps !== null) return
    getScps()
      .then((data) => setScps(sortScpsByRating(data)))
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : String(e)))
  }, [open, scps])

  // Focus the search input every time the dialog opens; reset transient state.
  useEffect(() => {
    if (!open) return
    setQuery("")
    setDebounced("")
    setActive(0)
    setSubmitError(null)
    inputRef.current?.focus()
  }, [open])

  // 200 ms debounce between keystrokes and filtering (AC5).
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 200)
    return () => clearTimeout(t)
  }, [query])

  const filtered = useMemo(
    () => (scps ? filterScps(scps, debounced) : []),
    [scps, debounced],
  )

  // Keep the active option in range whenever the result set changes.
  useEffect(() => setActive(0), [debounced])

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => listRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 6,
  })

  // Scroll the active row into view when keyboard navigation moves it (AC6).
  useLayoutEffect(() => {
    if (filtered.length) virtualizer.scrollToIndex(active, { align: "auto" })
  }, [active, filtered.length, virtualizer])

  if (!open) return null

  const confirm = async (scp: ScpEntry | undefined) => {
    if (!scp || submitting) return
    // Send scp_id only; the server resolves scp_text by id (POST /runs). If a run
    // can't be created (e.g. no text for that id → 422), the error surfaces inline.
    setSubmitting(true)
    setSubmitError(null)
    try {
      const run = await createRun({ scp_id: scp.id })
      onCreated(run)
      onClose()
    } catch (e) {
      // Keep the dialog open, surface the error inline near the list (AC6).
      setSubmitError(e instanceof ApiError ? e.message : "실행 생성에 실패했습니다.")
    } finally {
      setSubmitting(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === "Enter") {
      e.preventDefault()
      confirm(filtered[active])
    } else if (e.key === "Escape") {
      onClose()
    }
  }

  const activeId = filtered[active] ? `scp-opt-${filtered[active].id}` : undefined

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="새 실행 — SCP 선택"
        className="w-[520px] max-w-full overflow-hidden rounded-lg border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-border p-5 pb-3.5">
          <h2 className="mb-3 text-[15px] font-semibold text-foreground">새 실행 — SCP 선택</h2>
          <input
            ref={inputRef}
            type="text"
            aria-label="SCP 검색"
            role="combobox"
            aria-expanded="true"
            aria-controls="scp-listbox"
            aria-activedescendant={activeId}
            placeholder="번호(096), 영어 이름(shy guy), ID(SCP-096)…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            className="w-full rounded-md border border-white/10 bg-white/[0.07] px-3 py-2 text-[13px] text-foreground outline-none placeholder:text-subtle-foreground focus:border-primary"
          />
        </div>

        <div className="flex items-center justify-between border-b border-border px-5 py-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-subtle-foreground">
            스코어 높은 순
          </span>
          <span className="text-[11px] text-subtle-foreground">
            {scps ? `${filtered.length}개 일치` : ""}
          </span>
        </div>

        {loadError ? (
          <div className="px-5 py-6 text-[13px] text-status-failed">{loadError}</div>
        ) : (
          <div
            ref={listRef}
            id="scp-listbox"
            role="listbox"
            aria-label="SCP 목록"
            className="max-h-[280px] overflow-y-auto"
          >
            <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
              {virtualizer.getVirtualItems().map((v) => {
                const scp = filtered[v.index]
                const isActive = v.index === active
                return (
                  <div
                    key={scp.id}
                    id={`scp-opt-${scp.id}`}
                    role="option"
                    aria-selected={isActive}
                    onClick={() => {
                      setActive(v.index)
                      confirm(scp)
                    }}
                    className={`absolute left-0 top-0 flex w-full items-center gap-3 border-b border-border px-5 ${
                      isActive ? "bg-primary/15" : "hover:bg-white/[0.04]"
                    }`}
                    style={{ height: ROW_HEIGHT, transform: `translateY(${v.start}px)` }}
                  >
                    <span className="min-w-[76px] font-mono text-[12px] font-bold text-foreground">
                      {scp.id}
                    </span>
                    <div className="flex flex-1 flex-col gap-0.5">
                      <span className="text-[13px] text-foreground">{scp.nickname}</span>
                      <span className="text-[11px] text-muted-foreground">{scp.object_class}</span>
                    </div>
                    <span className="text-right text-[11px] tabular-nums text-subtle-foreground">
                      ★ {scp.rating}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {submitError && (
          <div role="alert" className="border-t border-border px-5 py-2.5 text-[12px] text-status-failed">
            {submitError}
          </div>
        )}

        <div className="flex justify-end gap-2.5 border-t border-border p-3.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/10 px-3.5 py-1.5 text-[13px] text-muted-foreground"
          >
            취소
          </button>
          <button
            type="button"
            disabled={submitting || !filtered.length}
            onClick={() => confirm(filtered[active])}
            className="rounded-md bg-primary px-4 py-1.5 text-[13px] font-semibold text-primary-foreground disabled:opacity-50"
          >
            실행 시작
          </button>
        </div>
      </div>
    </div>
  )
}
