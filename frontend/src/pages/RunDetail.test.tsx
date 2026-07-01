import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, fireEvent, waitFor, act, within } from "@testing-library/react"
import { RunDetail } from "./RunDetail"

// ── Mock EventSource ────────────────────────────────────────────────────────
class MockEventSource {
  static instances: MockEventSource[] = []
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {}
  closed = false
  constructor(public url: string) {
    MockEventSource.instances.push(this)
  }
  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(cb)
  }
  emit(type: string, data: unknown) {
    for (const cb of this.listeners[type] ?? []) cb({ data: JSON.stringify(data) } as MessageEvent)
  }
  close() {
    this.closed = true
  }
}

const RUN = {
  id: "r1",
  scp_id: "SCP-096",
  status: "running",
  current_stage: "image",
  gate_states: null,
  langfuse_trace_url: "https://langfuse.example/trace/abc",
}

function mockFetch() {
  return vi.fn((url: string) => {
    if (url === "/runs/r1" || url === "/runs/r2") return Promise.resolve({ ok: true, status: 200, json: async () => ({ ...RUN, id: url.slice(6) }) })
    if (url.includes("/stages/image/artifacts"))
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          stage: "image",
          images: [{ scene_num: 1, shot_id: "s1", image_path: "workspace/r1/images/a.png" }],
        }),
      })
    // any other stage: not reached
    return Promise.resolve({ ok: false, status: 404 })
  })
}

beforeEach(() => {
  MockEventSource.instances = []
  vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource)
})
afterEach(() => vi.restoreAllMocks())

async function renderRunDetail() {
  vi.stubGlobal("fetch", mockFetch())
  render(<RunDetail runId="r1" />)
  await waitFor(() => expect(screen.getByRole("navigation")).toBeInTheDocument())
}

describe("RunDetail", () => {
  it("renders semantic nav/aside/main with a 240px sidebar (AC1)", async () => {
    await renderRunDetail()
    expect(screen.getByRole("navigation")).toBeInTheDocument()
    expect(screen.getByRole("complementary")).toHaveClass("w-60") // <aside>, 240px
    expect(screen.getByRole("main")).toBeInTheDocument()
  })

  it("renders all five stages in fixed order (AC1)", async () => {
    await renderRunDetail()
    const aside = screen.getByRole("complementary")
    const tokens = [...aside.querySelectorAll("span.font-mono")].map((n) => n.textContent)
    expect(tokens.slice(0, 5)).toEqual(["scenario", "image", "tts", "subtitle", "video"])
  })

  it("renders the Langfuse trace link when available (AC1)", async () => {
    await renderRunDetail()
    expect(screen.getByRole("link", { name: /trace|Langfuse|트레이스/i })).toHaveAttribute(
      "href",
      "https://langfuse.example/trace/abc",
    )
  })

  it("renders a keyboard-focusable A/B comparison entry point", async () => {
    await renderRunDetail()
    expect(screen.getByRole("button", { name: "A/B 비교" })).toHaveClass("focus-visible:ring-2")
  })

  it("muted, non-clickable sidebar item for a not-yet-reached stage (AC8)", async () => {
    await renderRunDetail()
    // video is unreached (current_stage=image) → aria-disabled, not a button
    const video = screen.getByText("video").closest("[aria-disabled]")
    expect(video).toHaveAttribute("aria-disabled", "true")
  })

  it("stage_entry SSE event makes a new stage reachable without reload (AC9)", async () => {
    await renderRunDetail()
    // tts starts unreached (not a button)
    expect(screen.getByText("tts").closest("button")).toBeNull()
    act(() => MockEventSource.instances[0].emit("stage_entry", { run_id: "r1", stage: "tts" }))
    await waitFor(() => expect(screen.getByText("tts").closest("button")).not.toBeNull())
  })

  it("closes the EventSource on unmount", async () => {
    vi.stubGlobal("fetch", mockFetch())
    const { unmount } = render(<RunDetail runId="r1" />)
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0))
    unmount()
    expect(MockEventSource.instances.every((es) => es.closed)).toBe(true)
  })

  it("closes the EventSource when run id changes", async () => {
    vi.stubGlobal("fetch", mockFetch())
    const { rerender } = render(<RunDetail runId="r1" />)
    await waitFor(() => expect(MockEventSource.instances[0]).toBeTruthy())
    rerender(<RunDetail runId="r2" />)
    await waitFor(() => expect(MockEventSource.instances[1]).toBeTruthy())
    expect(MockEventSource.instances[0].closed).toBe(true)
    expect(MockEventSource.instances[1].url).toBe("/runs/r2/progress")
  })

  it("asks for confirmation before leaving a stage with dirty edits", async () => {
    const run = { ...RUN, current_stage: "subtitle", gate_states: null }
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, json: async () => run })
      if (url.includes("/stages/scenario/artifacts"))
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ stage: "scenario", scenes: [{ scene_num: 1, narration: "초안" }] }),
        })
      if (url.includes("/stages/subtitle/artifacts"))
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ stage: "subtitle", subtitles: [] }),
        })
      if (init?.method === "PATCH") return Promise.resolve({ ok: true, status: 200, text: async () => "" })
      return Promise.resolve({ ok: false, status: 404 })
    })
    vi.stubGlobal("fetch", fetchMock)
    const confirm = vi.fn().mockReturnValue(false)
    vi.stubGlobal("confirm", confirm)

    render(<RunDetail runId="r1" />)
    const sidebar = await screen.findByRole("complementary")
    await waitFor(() => expect(within(sidebar).getByText("subtitle").closest("button")).toBeInTheDocument())
    fireEvent.click(within(sidebar).getByText("scenario").closest("button")!)
    await waitFor(() => expect(screen.getByRole("button", { name: "편집" })).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "편집" }))
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "수정 중" } })
    fireEvent.click(within(sidebar).getByText("subtitle").closest("button")!)

    expect(confirm).toHaveBeenCalledWith("저장하지 않은 변경사항이 있습니다. 계속하시겠습니까?")
    expect(screen.getByRole("textbox")).toHaveValue("수정 중")
  })
})
