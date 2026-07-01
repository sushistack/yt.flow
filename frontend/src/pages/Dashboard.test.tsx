import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import { Dashboard } from "@/pages/Dashboard"
import type { Run } from "@/lib/types"

const run = (id: string, status: Run["status"], started_at: string): Run => ({
  id,
  scp_id: id,
  status,
  current_stage: "image",
  gate_states: null,
  started_at,
  updated_at: started_at,
})

function mockFetch(handler: (url: string) => { ok: boolean; body?: unknown } | "network-error") {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const r = handler(url)
    if (r === "network-error") throw new TypeError("failed to fetch")
    return { ok: r.ok, status: r.ok ? 200 : 500, json: async () => r.body } as Response
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe("Dashboard", () => {
  it("shows skeleton rows while runs are loading", () => {
    mockFetch(() => ({ ok: true, body: new Promise(() => {}) })) // never resolves body
    const { container } = render(<Dashboard />)
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0)
  })

  it("shows the empty state when no runs exist", async () => {
    mockFetch((u) => (u === "/runs" ? { ok: true, body: [] } : { ok: true, body: [] }))
    render(<Dashboard />)
    expect(await screen.findByText("실행 없음. 새 실행을 시작하세요.")).toBeInTheDocument()
  })

  it("shows the API-down banner when /runs is unreachable", async () => {
    mockFetch(() => "network-error")
    render(<Dashboard />)
    expect(
      await screen.findByText("서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요."),
    ).toBeInTheDocument()
  })

  it("lists runs with awaiting_approval floated to the top", async () => {
    mockFetch(() => ({
      ok: true,
      body: [
        run("SCP-049", "running", "2026-07-01T10:00:00Z"),
        run("SCP-173", "awaiting_approval", "2026-07-01T08:00:00Z"),
      ],
    }))
    render(<Dashboard />)
    const list = await screen.findByText("SCP-173")
    // Both rows present, awaiting first in DOM order.
    const ids = screen.getAllByText(/SCP-\d+/).map((n) => n.textContent)
    expect(list).toBeInTheDocument()
    expect(ids[0]).toBe("SCP-173")
  })
})
