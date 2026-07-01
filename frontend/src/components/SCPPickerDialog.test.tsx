import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { SCPPickerDialog } from "@/components/SCPPickerDialog"
import type { ScpEntry } from "@/lib/types"

const scp = (id: string, nickname: string, rating: number, scp_text?: string): ScpEntry => ({
  id,
  nickname,
  object_class: "Euclid",
  rating,
  scp_text,
})

beforeAll(() => {
  // @tanstack/react-virtual needs ResizeObserver + a measurable scroll element,
  // neither of which jsdom provides. Give the container a fixed viewport height.
  // Fire the callback on observe so @tanstack/react-virtual measures the element
  // (it reads getBoundingClientRect inside the callback) instead of staying at 0.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      cb: ResizeObserverCallback
      constructor(cb: ResizeObserverCallback) {
        this.cb = cb
      }
      observe() {
        this.cb([], this)
      }
      unobserve() {}
      disconnect() {}
    },
  )
  // virtual-core reads offsetHeight/offsetWidth for the scroll-element rect.
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 280 })
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 520 })
  HTMLElement.prototype.scrollTo = () => {}
})

function mockScps(list: ScpEntry[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/scps") return { ok: true, status: 200, json: async () => list } as Response
      if (url === "/runs" && init?.method === "POST")
        return {
          ok: true,
          status: 201,
          json: async () => ({
            id: "new-run",
            scp_id: JSON.parse(String(init.body)).scp_id,
            status: "running",
            current_stage: "scenario",
            gate_states: null,
            started_at: "2026-07-01T12:00:00Z",
            updated_at: "2026-07-01T12:00:00Z",
          }),
        } as Response
      throw new Error(`unexpected ${init?.method ?? "GET"} ${url}`)
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

const THREE = [
  scp("SCP-173", "The Sculpture", 4.9, "text-173"),
  scp("SCP-096", "The Shy Guy", 4.8, "text-096"),
  scp("SCP-049", "Plague Doctor", 4.5, "text-049"),
]

describe("SCPPickerDialog", () => {
  it("focuses the search input every time it opens", async () => {
    mockScps(THREE)
    render(<SCPPickerDialog open onClose={() => {}} onCreated={() => {}} />)
    const input = screen.getByRole("combobox", { name: "SCP 검색" })
    await waitFor(() => expect(document.activeElement).toBe(input))
  })

  it("exposes listbox/option roles and updates aria-activedescendant on Up/Down", async () => {
    mockScps(THREE)
    render(<SCPPickerDialog open onClose={() => {}} onCreated={() => {}} />)
    await screen.findByRole("listbox")
    const input = screen.getByRole("combobox", { name: "SCP 검색" })
    // Sorted rating-desc: 173, 096, 049. Active starts at index 0 (173).
    expect(input).toHaveAttribute("aria-activedescendant", "scp-opt-SCP-173")
    fireEvent.keyDown(input, { key: "ArrowDown" })
    expect(input).toHaveAttribute("aria-activedescendant", "scp-opt-SCP-096")
    fireEvent.keyDown(input, { key: "ArrowUp" })
    expect(input).toHaveAttribute("aria-activedescendant", "scp-opt-SCP-173")
  })

  it("filters by numeric ID after the 200ms debounce", async () => {
    vi.useFakeTimers()
    mockScps(THREE)
    render(<SCPPickerDialog open onClose={() => {}} onCreated={() => {}} />)
    // flush the getScps promise
    await vi.waitFor(() => expect(screen.queryAllByRole("option").length).toBeGreaterThan(0))
    const input = screen.getByRole("combobox", { name: "SCP 검색" })
    fireEvent.change(input, { target: { value: "096" } })
    vi.advanceTimersByTime(200)
    await vi.waitFor(() => {
      const ids = screen.getAllByRole("option").map((o) => o.id)
      expect(ids).toEqual(["scp-opt-SCP-096"])
    })
    vi.useRealTimers()
  })

  it("virtualizes a 2000-item list (rendered options far below full count)", async () => {
    const big = Array.from({ length: 2000 }, (_, i) => scp(`SCP-${1000 + i}`, `n${i}`, 4 - i / 1000, "t"))
    mockScps(big)
    render(<SCPPickerDialog open onClose={() => {}} onCreated={() => {}} />)
    await screen.findByRole("listbox")
    await waitFor(() => expect(screen.getAllByRole("option").length).toBeGreaterThan(0))
    expect(screen.getAllByRole("option").length).toBeLessThan(100)
  })

  it("creates a run on Enter: POSTs, calls onCreated, and closes", async () => {
    mockScps(THREE)
    const onCreated = vi.fn()
    const onClose = vi.fn()
    render(<SCPPickerDialog open onClose={onClose} onCreated={onCreated} />)
    const input = await screen.findByRole("combobox", { name: "SCP 검색" })
    await screen.findByRole("listbox")
    fireEvent.keyDown(input, { key: "ArrowDown" }) // → SCP-096
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(onCreated).toHaveBeenCalledOnce())
    expect(onCreated.mock.calls[0][0].scp_id).toBe("SCP-096")
    expect(onClose).toHaveBeenCalledOnce()
  })

  it("keeps the dialog open and shows an inline error when POST fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/scps") return { ok: true, status: 200, json: async () => THREE } as Response
        return { ok: false, status: 500, json: async () => ({}) } as Response
      }),
    )
    const onClose = vi.fn()
    render(<SCPPickerDialog open onClose={onClose} onCreated={() => {}} />)
    const input = await screen.findByRole("combobox", { name: "SCP 검색" })
    await screen.findByRole("listbox")
    fireEvent.keyDown(input, { key: "Enter" })
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it("posts scp_id only — the server resolves scp_text (no text carried by the frontend)", async () => {
    // GET /scps returns summary rows without scp_text; the picker must still POST.
    const summaryOnly = [scp("SCP-999", "No Body", 4.0)] // scp_text undefined
    let postBody: unknown
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/scps") return { ok: true, status: 200, json: async () => summaryOnly } as Response
        postBody = JSON.parse(String(init?.body))
        return { ok: true, status: 201, json: async () => ({ id: "r", scp_id: "SCP-999" }) } as Response
      }),
    )
    const onCreated = vi.fn()
    render(<SCPPickerDialog open onClose={() => {}} onCreated={onCreated} />)
    const input = await screen.findByRole("combobox", { name: "SCP 검색" })
    await screen.findByRole("listbox")
    fireEvent.keyDown(input, { key: "Enter" })
    await waitFor(() => expect(onCreated).toHaveBeenCalledOnce())
    expect(postBody).toEqual({ scp_id: "SCP-999" }) // no scp_text
  })
})
