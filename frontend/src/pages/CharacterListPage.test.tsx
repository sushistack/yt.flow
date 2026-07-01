import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { CharacterListPage } from "@/pages/CharacterListPage"
import * as api from "@/lib/api"
import type { Character } from "@/lib/types"

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api")
  return { ...actual }
})

const mockChar: Character = {
  id: "char-1",
  scp_id: "SCP-096",
  canonical_name: "The Shy Guy",
  aliases: ["Shy Guy"],
  visual_descriptor: "A tall, pale humanoid entity with elongated limbs.",
  style_guide: null,
  image_prompt_base: null,
  selected_image_path: null,
  angle_front_path: "/tmp/front.png",
  angle_back_path: null,
  angle_side_path: null,
  angle_three_quarter_path: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
}

describe("CharacterListPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it("shows loading skeleton while fetching", () => {
    vi.spyOn(api, "getCharacters").mockReturnValue(new Promise(() => {}))
    render(<CharacterListPage />)
    // Skeleton pulsing divs exist
    const skeletons = document.querySelectorAll(".animate-pulse")
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it("shows empty state when no characters", async () => {
    vi.spyOn(api, "getCharacters").mockResolvedValue([])
    render(<CharacterListPage />)
    await waitFor(() => {
      expect(screen.getByText("등록된 캐릭터가 없습니다")).toBeTruthy()
    })
  })

  it("shows character list with SCP ID and name", async () => {
    vi.spyOn(api, "getCharacters").mockResolvedValue([mockChar])
    render(<CharacterListPage />)
    await waitFor(() => {
      expect(screen.getByText("SCP-096")).toBeTruthy()
      expect(screen.getByText("The Shy Guy")).toBeTruthy()
    })
  })

  it("shows angle count badge", async () => {
    vi.spyOn(api, "getCharacters").mockResolvedValue([mockChar])
    render(<CharacterListPage />)
    await waitFor(() => {
      expect(screen.getByText("1/4 각도")).toBeTruthy()
    })
  })

  it("shows descriptor preview truncated", async () => {
    const longDesc = "A" + "very long description. ".repeat(20)
    vi.spyOn(api, "getCharacters").mockResolvedValue([{ ...mockChar, visual_descriptor: longDesc }])
    render(<CharacterListPage />)
    await waitFor(() => {
      const truncated = screen.getByText((content) => content.includes("…") || content.includes("…"))
      expect(truncated).toBeTruthy()
    })
  })

  it('opens create dialog on "새 캐릭터" click', async () => {
    vi.spyOn(api, "getCharacters").mockResolvedValue([])
    render(<CharacterListPage />)
    await waitFor(() => {
      const btn = screen.getByText("+ 새 캐릭터")
      fireEvent.click(btn)
    })
    await waitFor(() => {
      expect(screen.getByRole("dialog")).toBeTruthy()
    })
  })

  it("navigates to detail on card click", async () => {
    const navSpy = vi.spyOn(await import("@/lib/navigate"), "navigate")
    vi.spyOn(api, "getCharacters").mockResolvedValue([mockChar])
    render(<CharacterListPage />)
    await waitFor(() => {
      fireEvent.click(screen.getByText("The Shy Guy"))
    })
    expect(navSpy).toHaveBeenCalledWith("/characters/char-1")
  })
})
