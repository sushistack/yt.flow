import { useEffect, useRef, useState } from "react"
import { ApiError, createCharacter, updateCharacter } from "@/lib/api"
import type { Character } from "@/lib/types"

type Props = {
  open: boolean
  onClose: () => void
  onCreated: () => void
  initial?: Character | null // null for create, Character for edit
}

export function CharacterFormDialog({ open, onClose, onCreated, initial }: Props) {
  const [scpId, setScpId] = useState("")
  const [canonicalName, setCanonicalName] = useState("")
  const [aliasesInput, setAliasesInput] = useState("")
  const [aliases, setAliases] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({})
  const inputRef = useRef<HTMLInputElement>(null)
  const isEdit = !!initial

  useEffect(() => {
    if (!open) return
    if (initial) {
      setScpId(initial.scp_id)
      setCanonicalName(initial.canonical_name)
      setAliases(initial.aliases || [])
      setAliasesInput("")
    } else {
      setScpId("")
      setCanonicalName("")
      setAliases([])
      setAliasesInput("")
    }
    setError(null)
    setValidationErrors({})
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [open, initial])

  const validate = (): boolean => {
    const errs: Record<string, string> = {}
    if (!scpId.trim()) errs.scpId = "SCP ID는 필수입니다"
    if (!canonicalName.trim()) errs.canonicalName = "이름은 필수입니다"
    setValidationErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleAddAlias = () => {
    const trimmed = aliasesInput.trim()
    if (trimmed && !aliases.includes(trimmed)) {
      setAliases((prev) => [...prev, trimmed])
      setAliasesInput("")
    }
  }

  const handleRemoveAlias = (alias: string) => {
    setAliases((prev) => prev.filter((a) => a !== alias))
  }

  const handleSubmit = async () => {
    if (submitting) return  // guard against double-submit
    if (!validate()) return
    setSubmitting(true)
    setError(null)
    try {
      if (isEdit && initial) {
        await updateCharacter(initial.id, {
          canonical_name: canonicalName.trim(),
          aliases,
        })
      } else {
        await createCharacter({
          scp_id: scpId.trim(),
          canonical_name: canonicalName.trim(),
          aliases,
        })
      }
      onCreated()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "저장에 실패했습니다.")
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-label={isEdit ? "캐릭터 편집" : "새 캐릭터"}>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/60" onClick={onClose} aria-hidden="true" />
      {/* Dialog */}
      <div className="relative z-10 w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-xl">
        <h2 className="mb-4 text-[16px] font-semibold text-foreground">
          {isEdit ? "캐릭터 편집" : "새 캐릭터"}
        </h2>

        {error && (
          <div role="alert" className="mb-3 rounded bg-status-failed-bg px-3 py-2 text-[12px] text-status-failed">
            {error}
          </div>
        )}

        <div className="space-y-3">
          {/* SCP ID */}
          <div>
            <label htmlFor="char-scd-id" className="block mb-1 text-[12px] font-medium text-muted-foreground">
              SCP ID
            </label>
            <input
              ref={inputRef}
              id="char-scd-id"
              type="text"
              value={scpId}
              onChange={(e) => setScpId(e.target.value)}
              disabled={isEdit}
              placeholder="예: SCP-096"
              className={`w-full rounded border ${validationErrors.scpId ? "border-status-failed" : "border-border"} bg-background px-3 py-2 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50`}
              aria-invalid={!!validationErrors.scpId}
              aria-describedby={validationErrors.scpId ? "char-scp-error" : undefined}
            />
            {validationErrors.scpId && (
              <p id="char-scp-error" className="mt-1 text-[11px] text-status-failed">{validationErrors.scpId}</p>
            )}
          </div>

          {/* Canonical Name */}
          <div>
            <label htmlFor="char-name" className="block mb-1 text-[12px] font-medium text-muted-foreground">
              이름
            </label>
            <input
              id="char-name"
              type="text"
              value={canonicalName}
              onChange={(e) => setCanonicalName(e.target.value)}
              placeholder="예: The Shy Guy"
              className={`w-full rounded border ${validationErrors.canonicalName ? "border-status-failed" : "border-border"} bg-background px-3 py-2 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-primary`}
              aria-invalid={!!validationErrors.canonicalName}
              aria-describedby={validationErrors.canonicalName ? "char-name-error" : undefined}
            />
            {validationErrors.canonicalName && (
              <p id="char-name-error" className="mt-1 text-[11px] text-status-failed">{validationErrors.canonicalName}</p>
            )}
          </div>

          {/* Aliases Tag Input */}
          <div>
            <label htmlFor="char-aliases" className="block mb-1 text-[12px] font-medium text-muted-foreground">
              별칭
            </label>
            <div className="flex gap-1.5">
              <input
                id="char-aliases"
                type="text"
                value={aliasesInput}
                onChange={(e) => setAliasesInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAddAlias() } }}
                placeholder="추가할 별칭 입력"
                className="flex-1 rounded border border-border bg-background px-3 py-2 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <button
                type="button"
                onClick={handleAddAlias}
                disabled={!aliasesInput.trim()}
                className="rounded border border-border px-3 py-2 text-[12px] text-muted-foreground hover:bg-card-hover disabled:opacity-30 transition-colors"
              >
                추가
              </button>
            </div>
            {aliases.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {aliases.map((alias) => (
                  <span key={alias} className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-[12px] text-foreground">
                    {alias}
                    <button
                      type="button"
                      onClick={() => handleRemoveAlias(alias)}
                      className="ml-0.5 text-muted-foreground hover:text-status-failed transition-colors"
                      aria-label={`${alias} 제거`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-cta border border-border px-4 py-2 text-[13px] text-muted-foreground hover:bg-card-hover transition-colors"
          >
            취소
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-cta bg-primary px-4 py-2 text-[13px] font-semibold text-primary-foreground disabled:opacity-50 transition-opacity"
          >
            {submitting ? "저장 중…" : isEdit ? "저장" : "생성"}
          </button>
        </div>
      </div>
    </div>
  )
}
