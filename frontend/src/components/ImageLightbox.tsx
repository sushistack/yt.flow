import { useEffect, useRef } from "react"

export type LightboxImage = { src: string; alt: string }

type Props = {
  images: LightboxImage[]
  index: number
  onIndexChange: (index: number) => void
  onClose: () => void
}

// Fullscreen image viewer. ponytail: hand-rolled dialog instead of shadcn/Radix —
// Dialog isn't installed, and the requirements (Esc, arrows, focus restore) are a
// keydown handler + focus save/restore, not worth a new dependency. Swap to
// shadcn Dialog if one gets generated later.
export function ImageLightbox({ images, index, onIndexChange, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null)

  // Save/restore focus so the keyboard returns to the thumbnail that opened us (AC4).
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    return () => opener?.focus()
  }, [])

  // Arrow nav (clamped, no wrap) + Esc close. `index` is read via a ref-free
  // closure re-created each render, so the handler always sees the current index.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") return onClose()
      if (e.key === "ArrowRight" && index < images.length - 1) onIndexChange(index + 1)
      if (e.key === "ArrowLeft" && index > 0) onIndexChange(index - 1)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [index, images.length, onIndexChange, onClose])

  const current = images[index]
  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={`이미지 ${index + 1} / ${images.length}`}
      tabIndex={-1}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-6 focus:outline-none"
    >
      <img
        src={current.src}
        alt={current.alt}
        onClick={(e) => e.stopPropagation()}
        className="max-h-full max-w-full object-contain"
      />
      <button
        type="button"
        onClick={onClose}
        aria-label="닫기"
        className="absolute right-4 top-4 rounded-md px-3 py-1 text-[13px] text-white/90 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        ✕
      </button>
      <span className="absolute bottom-4 font-mono text-[11px] text-white/70">
        {index + 1} / {images.length}
      </span>
    </div>
  )
}
