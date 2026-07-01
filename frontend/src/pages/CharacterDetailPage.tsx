import { useCallback, useEffect, useMemo, useState } from "react"
import { ApiError, deleteCharacter, getCharacter, getCharacterCandidates, getCharacterRefs, updateCharacter } from "@/lib/api"
import { navigate } from "@/lib/navigate"
import type { CharacterDetail, CharacterCandidate, ReferenceImage } from "@/lib/types"
import { AngleGallery } from "@/components/characters/AngleGallery"
import { ReferenceSearchPanel } from "@/components/characters/ReferenceSearchPanel"
import { CandidatePanel } from "@/components/characters/CandidatePanel"
import { CharacterFormDialog } from "@/components/characters/CharacterFormDialog"

type Props = { charId: string }

export function CharacterDetailPage({ charId }: Props) {
  const [char, setChar] = useState<CharacterDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<CharacterCandidate[]>([])
  const [references, setReferences] = useState<ReferenceImage[]>([])
  const [descriptorEditing, setDescriptorEditing] = useState(false)
  const [descriptorDraft, setDescriptorDraft] = useState("")
  const [saving, setSaving] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const load = useCallback(() => {
    getCharacter(charId)
      .then((data) => {
        setChar(data)
        setCandidates(data.candidates || [])
        setReferences(data.references || [])
        setDescriptorDraft(data.visual_descriptor || "")
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)))
  }, [charId])

  useEffect(() => void load(), [load])

  // Poll candidates when any are in generating state
  const hasGenerating = useMemo(
    () => candidates.some((c) => c.status === "pending" || c.status === "generating"),
    [candidates],
  )
  useEffect(() => {
    if (!hasGenerating) return
    const interval = setInterval(() => {
      getCharacterCandidates(charId).then(setCandidates).catch(() => {})
    }, 3000)
    return () => clearInterval(interval)
  }, [hasGenerating, charId])

  const handleRefsUpdated = (refs: ReferenceImage[]) => {
    setReferences(refs)
    void load()
  }

  const handleCandidatesRefresh = () => {
    getCharacterCandidates(charId).then(setCandidates).catch(() => {})
  }

  const handleSaveDescriptor = async () => {
    setSaving(true)
    try {
      const updated = await updateCharacter(charId, { visual_descriptor: descriptorDraft })
      setChar((prev) => prev ? { ...prev, ...updated } : prev)
      setDescriptorEditing(false)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "저장에 실패했습니다.")
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    setDeleteConfirm(false)
    try {
      await deleteCharacter(charId)
      navigate("/characters")
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "삭제에 실패했습니다.")
    }
  }

  const handleCharacterUpdated = () => {
    setEditDialogOpen(false)
    void load()
  }

  if (!char) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        {error ? (
          <div className="text-center">
            <p className="text-status-failed mb-4">{error}</p>
            <button type="button" onClick={() => navigate("/characters")} className="text-[13px] text-primary hover:underline">
              캐릭터 목록으로
            </button>
          </div>
        ) : (
          <div className="h-6 w-48 animate-pulse rounded bg-white/10" />
        )}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      <TopNav />
      {error && (
        <div role="alert" className="bg-status-failed-bg px-6 py-2.5 text-[12px] text-status-failed">
          {error}
        </div>
      )}
      <main className="mx-auto max-w-4xl p-6">
        {/* ── Header ─────────────────────────────────────────── */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-[18px] font-semibold text-foreground">{char.canonical_name}</h1>
            <span className="font-mono text-[13px] text-muted-foreground">{char.scp_id}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setEditDialogOpen(true)}
              className="rounded-cta border border-border px-4 py-1.5 text-[13px] text-foreground hover:bg-card-hover transition-colors"
            >
              편집
            </button>
            {!deleteConfirm ? (
              <button
                type="button"
                onClick={() => setDeleteConfirm(true)}
                className="rounded-cta border border-status-failed/30 px-4 py-1.5 text-[13px] text-status-failed hover:bg-status-failed-bg transition-colors"
              >
                삭제
              </button>
            ) : (
              <span className="flex items-center gap-1">
                <span className="text-[12px] text-status-failed">확실합니까?</span>
                <button type="button" onClick={handleDelete} className="rounded bg-status-failed px-2 py-1 text-[12px] text-white">예</button>
                <button type="button" onClick={() => setDeleteConfirm(false)} className="rounded border border-border px-2 py-1 text-[12px] text-muted-foreground">아니오</button>
              </span>
            )}
          </div>
        </div>

        {/* ── Angle Gallery ──────────────────────────────────── */}
        <section className="mb-6" aria-label="각도 갤러리">
          <h2 className="mb-3 text-[13px] font-semibold text-muted-foreground">각도 갤러리</h2>
          <AngleGallery character={char} />
        </section>

        {/* ── Descriptor Section ─────────────────────────────── */}
        <section className="mb-6 rounded-lg border border-border bg-card p-4" aria-label="시각적 설명">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-[13px] font-semibold text-muted-foreground">시각적 설명</h2>
            {!descriptorEditing ? (
              <button
                type="button"
                onClick={() => setDescriptorEditing(true)}
                className="text-[12px] text-primary hover:underline"
              >
                편집
              </button>
            ) : (
              <div className="flex gap-1">
                <button
                  type="button"
                  onClick={handleSaveDescriptor}
                  disabled={saving}
                  className="rounded bg-primary px-3 py-1 text-[12px] font-semibold text-primary-foreground disabled:opacity-50"
                >
                  {saving ? "저장 중…" : "저장"}
                </button>
                <button
                  type="button"
                  onClick={() => { setDescriptorEditing(false); setDescriptorDraft(char.visual_descriptor || "") }}
                  className="rounded border border-border px-3 py-1 text-[12px] text-muted-foreground"
                >
                  취소
                </button>
              </div>
            )}
          </div>
          {descriptorEditing ? (
            <textarea
              value={descriptorDraft}
              onChange={(e) => setDescriptorDraft(e.target.value)}
              rows={4}
              className="w-full rounded border border-border bg-background px-3 py-2 text-[13px] text-foreground focus:outline-none focus:ring-2 focus:ring-primary resize-y"
              aria-label="시각적 설명 편집"
            />
          ) : (
            <p className="text-[13px] text-foreground leading-relaxed whitespace-pre-wrap">
              {char.visual_descriptor || "아직 설명이 없습니다. 참조 이미지를 검색하면 Vision LLM이 자동으로 설명을 생성합니다."}
            </p>
          )}
        </section>

        {/* ── Aliases ─────────────────────────────────────────── */}
        {char.aliases.length > 0 && (
          <section className="mb-6" aria-label="별칭">
            <h2 className="mb-2 text-[13px] font-semibold text-muted-foreground">별칭</h2>
            <div className="flex flex-wrap gap-1.5">
              {char.aliases.map((alias, i) => (
                <span key={i} className="rounded-full border border-border bg-card px-2.5 py-0.5 text-[12px] text-foreground">
                  {alias}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* ── Reference Image Panel ───────────────────────────── */}
        <ReferenceSearchPanel
          charId={charId}
          references={references}
          onRefsUpdated={handleRefsUpdated}
        />

        {/* ── Candidate Generation Panel ──────────────────────── */}
        <CandidatePanel
          charId={charId}
          candidates={candidates}
          onCandidatesRefresh={handleCandidatesRefresh}
          hasReferences={references.length > 0}
        />
      </main>

      <CharacterFormDialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        onCreated={handleCharacterUpdated}
        initial={char}
      />
    </div>
  )
}

function TopNav() {
  return (
    <nav className="flex h-[52px] items-center border-b border-border px-6">
      <a
        href="/"
        onClick={(e) => { e.preventDefault(); navigate("/") }}
        className="text-[15px] font-semibold tracking-tight text-foreground"
      >
        yt<span className="text-primary">.</span>flow
      </a>
      <div className="ml-6 flex items-center gap-1">
        <a
          href="/"
          onClick={(e) => { e.preventDefault(); navigate("/") }}
          className="rounded px-3 py-1.5 text-[13px] text-muted-foreground transition-colors hover:bg-card-hover hover:text-foreground"
        >
          실행
        </a>
        <span className="rounded px-3 py-1.5 text-[13px] text-foreground bg-card-hover">캐릭터</span>
      </div>
    </nav>
  )
}
