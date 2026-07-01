import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { CardRow } from "./card-row"

describe("CardRow", () => {
  it("applies card-hover background and hairline bottom border (AC2)", () => {
    render(<CardRow onClick={() => {}}>SCP-096</CardRow>)
    const row = screen.getByRole("button", { name: "SCP-096" })
    expect(row).toHaveClass("bg-card", "hover:bg-card-hover", "border-b", "border-border")
  })

  it("is a keyboard-operable click target when onClick is given", () => {
    const onClick = vi.fn()
    render(<CardRow onClick={onClick}>row</CardRow>)
    fireEvent.click(screen.getByRole("button", { name: "row" }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it("renders a non-interactive div without onClick", () => {
    render(<CardRow>plain</CardRow>)
    expect(screen.queryByRole("button")).toBeNull()
    expect(screen.getByText("plain")).toHaveClass("bg-card", "hover:bg-card-hover")
  })

  it("disables the row when disabled", () => {
    render(
      <CardRow onClick={() => {}} disabled>
        row
      </CardRow>,
    )
    expect(screen.getByRole("button")).toBeDisabled()
  })
})
