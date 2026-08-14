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
    if (url === "/runs/r1" || url === "/runs/r2") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify({ ...RUN, id: url.slice(6) }) })
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

  it("run_failed SSE flips the failed stage to retryable without reload (D9)", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(RUN) })
      if (url.includes("/stages/image/retry")) return Promise.resolve({ ok: true, status: 202, text: async () => JSON.stringify({ run_id: "r1", stage: "image", status: "retrying" }) })
      // artifacts GET 404s: the failed stage never finished, mirrors the real E2E capture
      return Promise.resolve({ ok: false, status: 404 })
    })
    vi.stubGlobal("fetch", fetchMock)
    render(<RunDetail runId="r1" />)
    await waitFor(() => expect(screen.getByRole("navigation")).toBeInTheDocument())

    act(() => MockEventSource.instances[0].emit("run_failed", { run_id: "r1", stage: "image", error: "ComfyUI connection refused" }))

    const main = screen.getByRole("main")
    const retryBtn = await within(main).findByRole("button", { name: "재시도" })
    fireEvent.click(retryBtn)
    fireEvent.click(within(main).getByRole("button", { name: "확인" }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/runs/r1/stages/image/retry", expect.objectContaining({ method: "POST" })),
    )
    // AC1.2: exactly one retry request fires.
    const retryCalls = fetchMock.mock.calls.filter(([url]) => url === "/runs/r1/stages/image/retry")
    expect(retryCalls).toHaveLength(1)
  })

  it("retries a stage that was already failed on fresh load (regression guard)", async () => {
    const run = { ...RUN, status: "failed", gate_states: JSON.stringify({ image: "failed" }) }
    const fetchMock = vi.fn((url: string) => {
      if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(run) })
      if (url.includes("/stages/image/retry")) return Promise.resolve({ ok: true, status: 202, text: async () => JSON.stringify({ run_id: "r1", stage: "image", status: "retrying" }) })
      return Promise.resolve({ ok: false, status: 404 })
    })
    vi.stubGlobal("fetch", fetchMock)
    render(<RunDetail runId="r1" />)

    const main = await screen.findByRole("main")
    const retryBtn = await within(main).findByRole("button", { name: "재시도" })
    fireEvent.click(retryBtn)
    fireEvent.click(within(main).getByRole("button", { name: "확인" }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/runs/r1/stages/image/retry", expect.objectContaining({ method: "POST" })),
    )
  })

  it("asks for confirmation before leaving a stage with dirty edits", async () => {
    const run = { ...RUN, current_stage: "subtitle", gate_states: null }
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(run) })
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

  // ── Story 12.3: the gate warning survives reload and arrives on gate_pending ──

  const QUALITY_WARNING = {
    final_pass_index: 2,
    retry_scope: "scene",
    review_overall_pass: false,
    critic_verdict: "retry",
    critic_feedback: "장면 2의 긴장이 풀립니다",
    rule_metrics: {
      aggregate: { character_count: 120, sentence_count: 8, duplicate_sentence_count: 1, repeated_4gram_count: 0 },
      scenes: [], repeated_ngrams: [], slop_phrase_hits: [], slop_vocabulary_version: 1,
    },
    grounded_contradictions: [],
    review_issues: [],
    warning: { code: "unresolved_pass2", message: "재검토 후에도 품질 문제가 남아 있습니다." },
  }

  function mockScenarioGate(quality: unknown | null) {
    const run = { ...RUN, current_stage: "scenario", status: "awaiting_approval", gate_states: JSON.stringify({ scenario: "pending" }) }
    const fetchMock = vi.fn((url: string) => {
      if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(run) })
      if (url.includes("/stages/scenario/artifacts"))
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ stage: "scenario", scenes: [{ scene_num: 1, narration: "초안" }], scenario_quality: quality }),
        })
      return Promise.resolve({ ok: false, status: 404 })
    })
    vi.stubGlobal("fetch", fetchMock)
    return fetchMock
  }

  it("a fresh load recovers the gate warning from artifacts, not from SSE (AC6)", async () => {
    mockScenarioGate(QUALITY_WARNING)
    render(<RunDetail runId="r1" />)
    // No SSE event is ever emitted here — the artifact endpoint is the authority.
    expect(await screen.findByRole("heading", { name: /2차 검토 경고/ })).toBeInTheDocument()
    expect(screen.getByRole("alert").textContent).toContain("재검토 후에도 품질 문제가 남아 있습니다.")
    expect(await screen.findByRole("button", { name: "승인" })).toBeInTheDocument()
  })

  it("a legacy run with no quality context renders the gate normally (AC6)", async () => {
    mockScenarioGate(null)
    render(<RunDetail runId="r1" />)
    expect(await screen.findByRole("button", { name: "승인" })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: /2차 검토 경고/ })).not.toBeInTheDocument()
  })

  it("scenario gate_pending re-reads artifacts so a new warning appears without reload", async () => {
    const fetchMock = mockScenarioGate(null)
    render(<RunDetail runId="r1" />)
    await screen.findByRole("button", { name: "승인" })
    const before = fetchMock.mock.calls.filter(([url]) => String(url).includes("/stages/scenario/artifacts")).length

    // The retried scenario now carries a warning; the SSE frame only triggers the re-read.
    mockScenarioGate(QUALITY_WARNING)
    act(() => MockEventSource.instances[0].emit("gate_pending", { run_id: "r1", stage: "scenario", scenario_quality: QUALITY_WARNING }))

    expect(await screen.findByRole("heading", { name: /2차 검토 경고/ })).toBeInTheDocument()
    expect(before).toBeGreaterThan(0)
  })

  // ── Story 13.1: run warnings arrive at NON-scenario gates too (AC5) ─────────

  const PLATE_WARNING = {
    code: "stock_plate_missing",
    stage: "image",
    message: "승인된 스톡 배경이 없어 배경을 생성했습니다",
    context: { scene_num: 3, shot_id: "S002", location_key: "corridor" },
  }

  function mockImageGate(warnings: unknown[]) {
    const run = { ...RUN, current_stage: "image", status: "awaiting_approval", gate_states: JSON.stringify({ scenario: "approved", image: "pending" }) }
    const fetchMock = vi.fn((url: string) => {
      if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(run) })
      if (url.includes("/stages/image/artifacts"))
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ stage: "image", images: [{ scene_num: 1, shot_id: "s1", image_path: "workspace/r1/images/a.png" }], warnings }),
        })
      return Promise.resolve({ ok: false, status: 404 })
    })
    vi.stubGlobal("fetch", fetchMock)
    return fetchMock
  }

  it("image gate_pending re-reads artifacts so run warnings appear without reload", async () => {
    mockImageGate([])
    render(<RunDetail runId="r1" />)
    await screen.findByRole("button", { name: "승인" })
    expect(screen.queryByRole("heading", { name: /경고 1건/ })).not.toBeInTheDocument()

    // Story 12.3 refreshed on the scenario gate only; the image stage writes warnings
    // of its own, so the refresh has to happen at every gate.
    mockImageGate([PLATE_WARNING])
    act(() => MockEventSource.instances[0].emit("gate_pending", { run_id: "r1", stage: "image", warnings: [PLATE_WARNING], warning_count: 1 }))

    expect(await screen.findByRole("heading", { name: /경고 1건/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "승인" })).toBeInTheDocument()
  })

  it("a gate_pending for another stage does not refetch the stage on screen", async () => {
    // The refetch nulls artifacts before re-fetching, so firing it for an unrelated
    // stage would throw away an in-progress narration edit in the panel.
    const run = { ...RUN, current_stage: "scenario", status: "awaiting_approval", gate_states: JSON.stringify({ scenario: "pending" }) }
    const fetchMock = vi.fn((url: string) => {
      if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(run) })
      if (url.includes("/stages/scenario/artifacts"))
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ stage: "scenario", scenes: [{ scene_num: 1, narration: "초안" }], warnings: [] }),
        })
      return Promise.resolve({ ok: false, status: 404 })
    })
    vi.stubGlobal("fetch", fetchMock)

    render(<RunDetail runId="r1" />)
    await screen.findByRole("button", { name: "편집" })
    fireEvent.click(screen.getByRole("button", { name: "편집" }))
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "수정 중" } })
    const before = fetchMock.mock.calls.filter(([url]) => String(url).includes("/stages/scenario/artifacts")).length

    act(() => MockEventSource.instances[0].emit("gate_pending", { run_id: "r1", stage: "image" }))

    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/stages/scenario/artifacts")).length).toBe(before),
    )
    expect(screen.getByRole("textbox")).toHaveValue("수정 중")
  })
})
