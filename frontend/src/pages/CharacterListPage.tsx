import { useEffect, useState } from "react"
import { ApiError, createCharacter, deleteCharacter, getCharacters } from "@/lib/api"
import { navigate } from "@/lib/navigate"
import type { Character } from "@/lib/types"
import { CardRow } from "@/components/common/card-row"
import { CharacterFormDialog } from "@/components/characters/CharacterFormDialog"

export function CharacterListPage() {
  const [chars, setChars] = useState<Character[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const load = () =>
    getCharacters()
      .then(setChars)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : String(e))
        setChars([])
      })

  useEffect(() => {
    void load()
  }, [])

  const handleCreated = () => {
    setDialogOpen(false)
    void load()
  }

  const handleDelete = async (id: string) => {
    if (!confirm("정말 삭제하시겠습니까? 관련된 모든 파일이 제거됩니다.")) return
    try {
      await deleteCharacter(id)
      void load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "삭제에 실패했습니다.")
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <TopNav onNew={() => setDialogOpen(true)} />
      {error && (
        <div role="alert" className="bg-status-failed-bg px-6 py-2.5 text-[12px] text-status-failed">
          {error}
        </div>
      )}
      <main className="p-6">
        <div className="mb-2.5 text-[13px] font-semibold text-muted-foreground">캐릭터 목록</div>
        {chars === null ? (
          <div className="overflow-hidden rounded-lg bg-card" aria-hidden="true">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3.5 border-b border-border px-4 py-3.5">
                <div className="h-4 w-[72px] animate-pulse rounded bg-white/10" />
                <div className="h-4 w-36 animate-pulse rounded bg-white/10" />
                <div className="ml-auto h-4 w-12 animate-pulse rounded bg-white/10" />
              </div>
            ))}
          </div>
        ) : chars.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-20 text-center">
            <p className="text-[13px] text-muted-foreground">등록된 캐릭터가 없습니다</p>
            <button
              type="button"
              onClick={() => setDialogOpen(true)}
              className="rounded-cta bg-primary px-4 py-2 text-[13px] font-semibold text-primary-foreground"
            >
              + 새 캐릭터
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg bg-card">
            {chars.map((char) => (
              <CardRow key={char.id} onClick={() => navigate(`/characters/${char.id}`)}>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[12px] text-primary min-w-[72px]">{char.scp_id}</span>
                  <span className="text-[14px] font-medium text-foreground">{char.canonical_name}</span>
                  {char.visual_descriptor && (
                    <span className="max-w-[300px] truncate text-[12px] text-muted-foreground">
                      {char.visual_descriptor.slice(0, 80)}{char.visual_descriptor.length > 80 ? "…" : ""}
                    </span>
                  )}
                </div>
                <div className="ml-auto flex items-center gap-3">
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {[char.angle_front_path, char.angle_back_path, char.angle_side_path, char.angle_three_quarter_path].filter(Boolean).length}/4 각도
                  </span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); void handleDelete(char.id) }}
                    className="rounded px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-status-failed-bg hover:text-status-failed transition-colors"
                    aria-label={`${char.canonical_name} 삭제`}
                  >
                    삭제
                  </button>
                </div>
              </CardRow>
            ))}
          </div>
        )}
      </main>
      <CharacterFormDialog open={dialogOpen} onClose={() => setDialogOpen(false)} onCreated={handleCreated} />
    </div>
  )
}

function TopNav({ onNew }: { onNew: () => void }) {
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
      <button
        type="button"
        onClick={onNew}
        className="ml-auto rounded-cta bg-primary px-[15px] py-[7px] text-[13px] font-semibold text-primary-foreground"
      >
        + 새 캐릭터
      </button>
    </nav>
  )
}
