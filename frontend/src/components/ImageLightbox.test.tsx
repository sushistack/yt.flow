import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { ImageLightbox } from "./ImageLightbox"

const IMAGES = [
  { src: "/files/r1/images/a.png", alt: "씬 1" },
  { src: "/files/r1/images/b.png", alt: "씬 2" },
  { src: "/files/r1/images/c.png", alt: "씬 3" },
]

describe("ImageLightbox", () => {
  it("renders the image at the given index in a modal dialog", () => {
    render(<ImageLightbox images={IMAGES} index={1} onIndexChange={() => {}} onClose={() => {}} />)
    const dialog = screen.getByRole("dialog")
    expect(dialog).toHaveAttribute("aria-modal", "true")
    expect(screen.getByRole("img")).toHaveAttribute("src", "/files/r1/images/b.png")
  })

  it("ArrowRight/ArrowLeft navigate between images (AC4)", () => {
    const onIndexChange = vi.fn()
    render(<ImageLightbox images={IMAGES} index={1} onIndexChange={onIndexChange} onClose={() => {}} />)
    fireEvent.keyDown(window, { key: "ArrowRight" })
    expect(onIndexChange).toHaveBeenCalledWith(2)
    fireEvent.keyDown(window, { key: "ArrowLeft" })
    expect(onIndexChange).toHaveBeenCalledWith(0)
  })

  it("clamps at the boundaries (no wrap)", () => {
    const onIndexChange = vi.fn()
    const { rerender } = render(
      <ImageLightbox images={IMAGES} index={0} onIndexChange={onIndexChange} onClose={() => {}} />,
    )
    fireEvent.keyDown(window, { key: "ArrowLeft" })
    rerender(<ImageLightbox images={IMAGES} index={2} onIndexChange={onIndexChange} onClose={() => {}} />)
    fireEvent.keyDown(window, { key: "ArrowRight" })
    expect(onIndexChange).not.toHaveBeenCalled()
  })

  it("Esc closes the lightbox (AC4)", () => {
    const onClose = vi.fn()
    render(<ImageLightbox images={IMAGES} index={0} onIndexChange={() => {}} onClose={onClose} />)
    fireEvent.keyDown(window, { key: "Escape" })
    expect(onClose).toHaveBeenCalled()
  })

  it("restores focus to the previously focused element on close", () => {
    const opener = document.createElement("button")
    document.body.appendChild(opener)
    opener.focus()
    expect(document.activeElement).toBe(opener)

    const { unmount } = render(
      <ImageLightbox images={IMAGES} index={0} onIndexChange={() => {}} onClose={() => {}} />,
    )
    expect(document.activeElement).not.toBe(opener) // focus moved into the dialog
    unmount()
    expect(document.activeElement).toBe(opener)
    opener.remove()
  })
})
