import { useState } from "react"
import { ApiError, fileUrl, searchCharacterRefs } from "@/lib/api"
import type { ReferenceImage } from "@/lib/types"

function safeHostname(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return url.length > 40 ? url.slice(0, 40) + "…" : url
  }
}

type Props = {
  charId: string
  references: ReferenceImage[]
  onRefsUpdated: (refs: ReferenceImage[]) => void
}

export function ReferenceSearchPanel({ charId, references, onRefsUpdated }: Props) {
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)

  const handleSearch = async () => {
    setSearching(true)
    setSearchError(null)
    try {
      const result = await searchCharacterRefs(charId)
      onRefsUpdated(result.references)
    } catch (e) {
      setSearchError(e instanceof ApiError ? e.message : "참조 이미지 검색에 실패했습니다.")
    } finally {
      setSearching(false)
    }
  }

  return (
    <section className="mb-6 rounded-lg border border-border bg-card p-4" aria-label="참조 이미지">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-[13px] font-semibold text-muted-foreground">참조 이미지</h2>
        <button
          type="button"
          onClick={handleSearch}
          disabled={searching}
          className="rounded-cta bg-primary px-4 py-1.5 text-[12px] font-semibold text-primary-foreground disabled:opacity-50 transition-opacity"
        >
          {searching ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
              검색 중…
            </span>
          ) : (
            "참조 이미지 검색"
          )}
        </button>
      </div>

      {searchError && (
        <div role="alert" className="mb-3 rounded bg-status-failed-bg px-3 py-2 text-[12px] text-status-failed">
          {searchError}
        </div>
      )}

      {searching && references.length === 0 ? (
        <div className="grid grid-cols-5 gap-2" aria-hidden="true">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="aspect-square animate-pulse rounded bg-white/10" />
          ))}
        </div>
      ) : references.length > 0 ? (
        <div className="grid grid-cols-5 gap-2">
          {references.map((ref) => (
            <div key={ref.id} className="group relative overflow-hidden rounded border border-border">
              <img
                src={fileUrl(ref.local_path)}
                alt=""
                className="aspect-square w-full object-cover"
                loading="lazy"
              />
              <a
                href={ref.url}
                target="_blank"
                rel="noopener noreferrer"
                className="absolute inset-0 flex items-end bg-black/40 p-1.5 opacity-0 group-hover:opacity-100 transition-opacity"
                aria-label="원본 이미지 열기"
              >
                <span className="text-[10px] text-white truncate">{safeHostname(ref.url)}</span>
              </a>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground py-4 text-center">
          "참조 이미지 검색"을 눌러 DuckDuckGo에서 SCP 캐릭터의 참조 이미지를 가져옵니다.
        </p>
      )}
    </section>
  )
}
