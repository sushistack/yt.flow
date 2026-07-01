import { describe, it, expect, afterEach } from "vitest"
import { render, screen, act } from "@testing-library/react"
import { navigate, usePathname } from "./navigate"

function Probe() {
  return <span>{usePathname()}</span>
}

afterEach(() => {
  window.history.pushState({}, "", "/")
})

describe("usePathname / navigate", () => {
  it("re-renders subscribers on navigate and reflects the current pathname", () => {
    act(() => navigate("/runs/abc"))
    render(<Probe />)
    expect(screen.getByText("/runs/abc")).toBeInTheDocument()
    act(() => navigate("/runs/xyz"))
    expect(screen.getByText("/runs/xyz")).toBeInTheDocument()
  })

  it("preserves the /app base path when the SPA is mounted under /app", () => {
    window.history.pushState({}, "", "/app")
    render(<Probe />)
    act(() => navigate("/runs/abc"))
    expect(screen.getByText("/app/runs/abc")).toBeInTheDocument()
    act(() => navigate("/"))
    expect(screen.getByText("/app/")).toBeInTheDocument()
  })
})
