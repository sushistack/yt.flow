import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { cleanup, render, screen, within } from "@testing-library/react"
import { RunAbComparisonPage } from "./RunAbComparisonPage"
import type { Run } from "@/lib/types"

const baseRun = (overrides: Partial<Run>): Run => ({
  id: "run-a",
  scp_id: "SCP-096",
  status: "complete",
  current_stage: "video",
  gate_states: null,
  prompt_variant: "A",
  ab_pair_id: null,
  started_at: "2026-07-01T10:00:00Z",
  updated_at: "2026-07-01T10:10:00Z",
  langfuse_trace_url: null,
  ...overrides,
})

const runA = baseRun({
  id: "run-a",
  prompt_variant: "A",
  ab_result: {
    winner: "A",
    reason: "Variant A가 더 안정적입니다.",
    llm_scores: {
      A: { atmosphere: 0.91, narrative_coherence: 0.84, article_fidelity: 0.88 },
      B: { atmosphere: 0.82, narrative_coherence: 0.76, article_fidelity: 0.8 },
    },
    rule_scores: {
      A: { scene_count_match: 1, subtitle_sync: 0.95, audio_duration_variance: 0.08 },
      B: { scene_count_match: 1, subtitle_sync: 0.88, audio_duration_variance: 0.14 },
    },
  },
})

const runB = baseRun({ id: "run-b", prompt_variant: "B", ab_pair_id: "run-a" })

type FetchMap = {
  run?: Run
  runs?: Run[]
  artifacts?: Record<string, unknown>
}

function mockFetch({ run = runA, runs = [runA, runB], artifacts = {} }: FetchMap = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url === `/runs/${run.id}`) return Promise.resolve({ ok: true, status: 200, json: async () => run })
      if (url === "/runs/run-a") return Promise.resolve({ ok: true, status: 200, json: async () => runA })
      if (url === "/runs/run-b") return Promise.resolve({ ok: true, status: 200, json: async () => runB })
      if (url === "/runs") return Promise.resolve({ ok: true, status: 200, json: async () => runs })
      const hit = artifacts[url]
      if (hit) return Promise.resolve({ ok: true, status: 200, json: async () => hit })
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) })
    }),
  )
}

beforeEach(() => {
  mockFetch()
})

afterEach(() => vi.restoreAllMocks())

describe("RunAbComparisonPage", () => {
  it("renders completed A/B scores, winner, and side-by-side variants", async () => {
    render(<RunAbComparisonPage runId="run-a" />)

    expect(await screen.findByRole("heading", { name: "A/B 비교" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "Variant A" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "Variant B" })).toBeInTheDocument()
    expect(screen.getByText("승자: Variant A")).toBeInTheDocument()
    expect(screen.getAllByText("atmosphere")).toHaveLength(2)
    expect(screen.getAllByText("narrative_coherence")).toHaveLength(2)
    expect(screen.getAllByText("article_fidelity")).toHaveLength(2)
    expect(screen.getAllByText("scene_count_match")).toHaveLength(2)
    expect(screen.getAllByText("subtitle_sync")).toHaveLength(2)
    expect(screen.getAllByText("audio_duration_variance")).toHaveLength(2)
  })

  it("resolves a selected B run back to the originating A run", async () => {
    mockFetch({ run: runB })
    render(<RunAbComparisonPage runId="run-b" />)

    const variantA = await screen.findByRole("region", { name: "Variant A" })
    const variantB = screen.getByRole("region", { name: "Variant B" })
    expect(within(variantA).getByText("run-a")).toBeInTheDocument()
    expect(within(variantB).getByText("run-b")).toBeInTheDocument()
  })

  it("shows a missing pair state", async () => {
    mockFetch({ run: baseRun({ id: "solo", ab_pair_id: null }), runs: [] })
    render(<RunAbComparisonPage runId="solo" />)

    expect(await screen.findByRole("status")).toHaveTextContent("연결된 B variant가 없습니다")
  })

  it("shows pair still running and failed states", async () => {
    mockFetch({ runs: [runA, baseRun({ id: "run-b", status: "running", ab_pair_id: "run-a" })] })
    render(<RunAbComparisonPage runId="run-a" />)
    expect(await screen.findByRole("status")).toHaveTextContent("Variant B 실행 중")

    cleanup()
    mockFetch({ runs: [runA, baseRun({ id: "run-b", status: "failed", ab_pair_id: "run-a" })] })
    render(<RunAbComparisonPage runId="run-a" />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Variant B 실패")
  })

  it("shows evaluation pending, tie, and no-winner states", async () => {
    mockFetch({ run: baseRun({ id: "run-a" }), runs: [baseRun({ id: "run-a" }), runB] })
    render(<RunAbComparisonPage runId="run-a" />)
    expect(await screen.findByRole("status")).toHaveTextContent("평가 대기")

    cleanup()
    mockFetch({
      run: baseRun({ id: "run-a", ab_result: { winner: "tie", reason: "동점입니다." } }),
      runs: [baseRun({ id: "run-a", ab_result: { winner: "tie", reason: "동점입니다." } }), runB],
    })
    render(<RunAbComparisonPage runId="run-a" />)
    expect(await screen.findByText("동점")).toBeInTheDocument()

    cleanup()
    mockFetch({
      run: baseRun({ id: "run-a", ab_result: { winner: null, reason: "품질 floor 미달" } }),
      runs: [baseRun({ id: "run-a", ab_result: { winner: null, reason: "품질 floor 미달" } }), runB],
    })
    render(<RunAbComparisonPage runId="run-a" />)
    expect(await screen.findByText("승자 없음")).toBeInTheDocument()
    expect(screen.getByText("품질 floor 미달")).toBeInTheDocument()
  })

  it("keeps stage tokens in English monospace and exposes keyboard-focusable stage controls", async () => {
    render(<RunAbComparisonPage runId="run-a" />)
    await screen.findByRole("heading", { name: "A/B 비교" })

    for (const stage of ["scenario", "image", "tts", "subtitle", "video"]) {
      const control = screen.getByRole("button", { name: stage })
      expect(control).toHaveClass("focus-visible:ring-2")
      expect(control.querySelector(".font-mono")).toHaveTextContent(stage)
    }
  })
})
