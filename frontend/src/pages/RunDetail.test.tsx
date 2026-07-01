import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react"
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
  emitRaw(type: string, data: string) {
    for (const cb of this.listeners[type] ?? []) cb({ data } as MessageEvent)
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
    if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, json: async () => RUN })
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

function mockFetchWithArtifactFailure() {
  return vi.fn((url: string) => {
    if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, json: async () => RUN })
    if (url.includes("/stages/image/artifacts")) return Promise.resolve({ ok: false, status: 500 })
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

  it("ignores malformed SSE payloads without breaking the detail page", async () => {
    await renderRunDetail()
    act(() => MockEventSource.instances[0].emitRaw("stage_entry", "{not json"))
    expect(screen.getByRole("main")).toBeInTheDocument()
  })

  it("stage_exit marks a stage reached without regressing the active current stage", async () => {
    await renderRunDetail()
    act(() => MockEventSource.instances[0].emit("stage_exit", { run_id: "r1", stage: "tts" }))
    await waitFor(() => expect(screen.getByText("tts").closest("button")).not.toBeNull())
    expect(screen.getByText("image").closest("[aria-current]")).toHaveAttribute("aria-current", "true")
  })

  it("shows an artifact error instead of the not-reached copy on non-404 failures", async () => {
    vi.stubGlobal("fetch", mockFetchWithArtifactFailure())
    render(<RunDetail runId="r1" />)
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("아티팩트를 불러올 수 없습니다"))
    expect(screen.queryByText("아직 실행되지 않은 스테이지입니다.")).not.toBeInTheDocument()
  })

  it("closes the EventSource on unmount", async () => {
    vi.stubGlobal("fetch", mockFetch())
    const { unmount } = render(<RunDetail runId="r1" />)
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0))
    unmount()
    expect(MockEventSource.instances.every((es) => es.closed)).toBe(true)
  })
})
