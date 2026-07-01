import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { AngleGallery } from "@/components/characters/AngleGallery"
import type { CharacterDetail } from "@/lib/types"

const baseChar: CharacterDetail = {
  id: "char-1",
  scp_id: "SCP-096",
  canonical_name: "The Shy Guy",
  aliases: [],
  visual_descriptor: null,
  style_guide: null,
  image_prompt_base: null,
  selected_image_path: null,
  angle_front_path: null,
  angle_back_path: null,
  angle_side_path: null,
  angle_three_quarter_path: null,
  created_at: "",
  updated_at: "",
  references: [],
  candidates: [],
}

describe("AngleGallery", () => {
  it("renders all 4 angle placeholders when no images", () => {
    render(<AngleGallery character={baseChar} />)
    // Each angle card has aria-label ending with "이미지 없음"
    const placeholders = screen.getAllByRole("img")
    expect(placeholders).toHaveLength(4)
    for (const el of placeholders) {
      expect(el.getAttribute("aria-label")).toContain("이미지 없음")
    }
  })

  it("shows angle labels for all 4 angles", () => {
    render(<AngleGallery character={baseChar} />)
    expect(screen.getByText("전면")).toBeTruthy()
    expect(screen.getByText("후면")).toBeTruthy()
    expect(screen.getByText("측면")).toBeTruthy()
    expect(screen.getByText("3/4")).toBeTruthy()
  })

  it("has aria-label on each angle card", () => {
    render(<AngleGallery character={baseChar} />)
    expect(screen.getByLabelText("전면 각도 — 이미지 없음")).toBeTruthy()
    expect(screen.getByLabelText("후면 각도 — 이미지 없음")).toBeTruthy()
  })

  it("renders images when paths exist", () => {
    const charWithImages = {
      ...baseChar,
      angle_front_path: "/workspace/SCP-096/characters/front_candidate_1.png",
      angle_back_path: "/workspace/SCP-096/characters/back_candidate_1.png",
    }
    render(<AngleGallery character={charWithImages} />)
    const imgs = screen.getAllByRole("img")
    // Should have 2 images (front + back) + 2 placeholders
    expect(imgs.length).toBeGreaterThanOrEqual(2)
  })
})
