import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { StageSidebarItem } from "./stage-sidebar-item"

describe("StageSidebarItem", () => {
  it("active stage: 2px primary left border + aria-current (AC4)", () => {
    render(<StageSidebarItem stage="scenario" active />)
    const item = screen.getByText("scenario").closest("[aria-current]")
    expect(item).toHaveAttribute("aria-current", "true")
    expect(item).toHaveClass("border-l-2", "border-l-primary", "bg-card")
  })

  it("renders the stage token in monospace", () => {
    render(<StageSidebarItem stage="image" />)
    expect(screen.getByText("image")).toHaveClass("font-mono")
  })

  it("pending gate: 2px purple left border + visible pending text (AC3)", () => {
    const { container } = render(<StageSidebarItem stage="image" gateState="pending" />)
    expect(container.firstElementChild).toHaveClass("border-l-2", "border-l-status-awaiting")
    expect(screen.getByText("승인 대기")).toBeInTheDocument()
  })

  it("approved/rejected gates show text + semantic color (AC3)", () => {
    const { rerender } = render(<StageSidebarItem stage="tts" gateState="approved" />)
    expect(screen.getByText("승인됨")).toHaveClass("text-status-approved")
    rerender(<StageSidebarItem stage="tts" gateState="rejected" />)
    expect(screen.getByText("거부됨")).toHaveClass("text-status-failed")
  })

  it("unreached stage: muted, aria-disabled, not clickable (AC5)", () => {
    const onSelect = vi.fn()
    render(<StageSidebarItem stage="video" reached={false} onSelect={onSelect} />)
    expect(screen.queryByRole("button")).toBeNull()
    const item = screen.getByText("video").closest("[aria-disabled]")
    expect(item).toHaveAttribute("aria-disabled", "true")
    expect(item).toHaveClass("opacity-50")
    if (item) fireEvent.click(item)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it("reached stage with onSelect is clickable", () => {
    const onSelect = vi.fn()
    render(<StageSidebarItem stage="subtitle" onSelect={onSelect} />)
    fireEvent.click(screen.getByRole("button"))
    expect(onSelect).toHaveBeenCalledWith("subtitle")
  })
})
