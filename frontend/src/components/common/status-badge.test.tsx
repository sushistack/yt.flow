import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { StatusBadge } from "./status-badge"

describe("StatusBadge", () => {
  it("renders running with amber token classes and 11px/500 sizing (AC1)", () => {
    render(<StatusBadge status="running" />)
    const badge = screen.getByText("실행 중")
    expect(badge).toHaveClass(
      "text-status-running",
      "bg-status-running-bg",
      "text-[11px]",
      "font-medium",
      "rounded-badge",
      "px-2",
      "py-[3px]",
    )
  })

  it("communicates status by text, not color alone (AC1)", () => {
    render(<StatusBadge status="awaiting_approval" />)
    expect(screen.getByText("승인 대기")).toBeInTheDocument()
  })

  it("maps gate states to semantic tones", () => {
    render(<StatusBadge status="approved" />)
    expect(screen.getByText("승인됨")).toHaveClass("text-status-approved", "bg-status-approved-bg")
  })

  it("maps complete and failed run statuses", () => {
    const { rerender } = render(<StatusBadge status="complete" />)
    expect(screen.getByText("완료")).toHaveClass("text-status-approved")
    rerender(<StatusBadge status="failed" />)
    expect(screen.getByText("실패")).toHaveClass("text-status-failed")
  })

  it("degrades to a muted badge on an out-of-union status instead of crashing", () => {
    // The API is a trust boundary; an unknown status must not blank the app.
    render(<StatusBadge status={"unknown_state" as never} />)
    expect(screen.getByText("unknown_state")).toHaveClass("text-muted-foreground")
  })
})
