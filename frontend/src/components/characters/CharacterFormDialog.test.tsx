import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { CharacterFormDialog } from "@/components/characters/CharacterFormDialog"
import * as api from "@/lib/api"

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api")
  return { ...actual }
})

describe("CharacterFormDialog", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it("renders create form when open", () => {
    render(<CharacterFormDialog open={true} onClose={vi.fn()} onCreated={vi.fn()} />)
    expect(screen.getByRole("dialog")).toBeTruthy()
    expect(screen.getByLabelText("SCP ID")).toBeTruthy()
    expect(screen.getByLabelText("이름")).toBeTruthy()
  })

  it("does not render when closed", () => {
    render(<CharacterFormDialog open={false} onClose={vi.fn()} onCreated={vi.fn()} />)
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("validates empty SCP ID", async () => {
    render(<CharacterFormDialog open={true} onClose={vi.fn()} onCreated={vi.fn()} />)
    const submitBtn = screen.getByText("생성")
    fireEvent.click(submitBtn)
    await waitFor(() => {
      expect(screen.getByText("SCP ID는 필수입니다")).toBeTruthy()
    })
  })

  it("validates empty name", async () => {
    render(<CharacterFormDialog open={true} onClose={vi.fn()} onCreated={vi.fn()} />)
    fireEvent.change(screen.getByLabelText("SCP ID"), { target: { value: "SCP-999" } })
    const submitBtn = screen.getByText("생성")
    fireEvent.click(submitBtn)
    await waitFor(() => {
      expect(screen.getByText("이름은 필수입니다")).toBeTruthy()
    })
  })

  it("calls createCharacter on valid submit", async () => {
    const createSpy = vi.spyOn(api, "createCharacter").mockResolvedValue({} as any)
    const onCreated = vi.fn()
    render(<CharacterFormDialog open={true} onClose={vi.fn()} onCreated={onCreated} />)
    fireEvent.change(screen.getByLabelText("SCP ID"), { target: { value: "SCP-999" } })
    fireEvent.change(screen.getByLabelText("이름"), { target: { value: "Tickle Monster" } })
    fireEvent.click(screen.getByText("생성"))
    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith({
        scp_id: "SCP-999",
        canonical_name: "Tickle Monster",
        aliases: [],
      })
    })
  })

  it("adds and removes aliases via tag input", async () => {
    render(<CharacterFormDialog open={true} onClose={vi.fn()} onCreated={vi.fn()} />)
    fireEvent.change(screen.getByLabelText("별칭"), { target: { value: "Alias1" } })
    fireEvent.click(screen.getByText("추가"))
    await waitFor(() => {
      expect(screen.getByText("Alias1")).toBeTruthy()
    })
    // Remove it
    fireEvent.click(screen.getByLabelText("Alias1 제거"))
    await waitFor(() => {
      expect(screen.queryByText("Alias1")).toBeNull()
    })
  })

  it("renders edit form when initial provided", () => {
    const initial = {
      id: "char-1",
      scp_id: "SCP-096",
      canonical_name: "The Shy Guy",
      aliases: ["Shy"],
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
    }
    render(<CharacterFormDialog open={true} onClose={vi.fn()} onCreated={vi.fn()} initial={initial} />)
    expect(screen.getByText("캐릭터 편집")).toBeTruthy()
    expect(screen.getByText("저장")).toBeTruthy()
    // SCP ID is disabled in edit mode
    const scpInput = screen.getByLabelText("SCP ID") as HTMLInputElement
    expect(scpInput.disabled).toBe(true)
  })
})
