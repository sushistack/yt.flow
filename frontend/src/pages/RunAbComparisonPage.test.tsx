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
  // REPLACED IN STORY 13.2, and the replacement is itself the regression guard.
  //
  // The previous fixture used `llm_scores` / `rule_scores` with keys
  // `scene_count_match` / `subtitle_sync` — a shape the backend has never produced.
  // Because the fixture and the component agreed with each other, the tests passed
  // while every score cell rendered "—" against a real `ab_result`. A fixture that
  // invents its own contract cannot catch a contract break; this one is copied from
  // eval_service's `_axis_scores_to_dict` / `_rule_metrics_to_dict` output, so if the
  // backend schema moves again, these tests are what notices. Same lesson as 7.5.
  //
  // Axis scores are the 1–5 judge scale (QUALITY_FLOOR is 2.0), not 0–1. The visual
  // pair (`unreadable_rate`, `mean_dsg_score`) is present here because this fixture
  // stands in for a run the offline scorer WAS run on; for most runs those two keys
  // are absent and the rows correctly render "—".
  ab_result: {
    winner: "A",
    reason: "Variant A가 더 안정적입니다.",
    // Three axes, no `total` — `_axis_scores_to_dict` does not emit one.
    axis_scores: {
      A: { atmosphere: 4.33, narrative_coherence: 4.0, article_fidelity: 4.67 },
      B: { atmosphere: 3.67, narrative_coherence: 3.33, article_fidelity: 4.0 },
    },
    rule_based_scores: {
      A: {
        scene_count_match_rate: 1,
        subtitle_sync_error: 0.35,
        audio_duration_variance: 0.25,
        cut_alignment_error: 0.12,
        motion_archetype_coverage: 1,
        motion_repeat_ratio: 0.0154,
        unreadable_rate: 0.182,
        mean_dsg_score: 0.61,
      },
      B: {
        scene_count_match_rate: 1,
        subtitle_sync_error: 0.1,
        audio_duration_variance: 0,
        cut_alignment_error: 0.4,
        motion_archetype_coverage: 0.8,
        motion_repeat_ratio: 0.0625,
        unreadable_rate: 0.27,
        mean_dsg_score: 0.54,
      },
    },
    pairwise_winner: { majority_winner: "A", majority_count: 2, total_runs: 2 },
    evaluated_at: "2026-07-01T10:11:00Z",
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
      if (url === `/runs/${run.id}`) return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(run) })
      if (url === "/runs/run-a") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(runA) })
      if (url === "/runs/run-b") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(runB) })
      if (url === "/runs") return Promise.resolve({ ok: true, status: 200, text: async () => JSON.stringify(runs) })
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
    // Row labels ARE the backend's metric keys (Story 13.2 corrected them from
    // `scene_count_match` / `subtitle_sync`, which the backend never emitted).
    for (const metric of [
      "scene_count_match_rate",
      "subtitle_sync_error",
      "audio_duration_variance",
      "cut_alignment_error",
      "motion_archetype_coverage",
      "motion_repeat_ratio",
      "unreadable_rate",
      "mean_dsg_score",
    ]) {
      expect(screen.getAllByText(metric)).toHaveLength(2)
    }
  })

  it("renders real backend score values instead of the not-measured placeholder", async () => {
    // The defect Story 13.2 closed: with the old key names every cell fell through to
    // formatScore(undefined) and rendered "결과 없음" on real data. Assert actual values,
    // not just that the rows exist — a label-only assertion is what let this survive.
    render(<RunAbComparisonPage runId="run-a" />)

    const variantA = await screen.findByRole("region", { name: "Variant A" })
    expect(within(variantA).getByText("4.33")).toBeInTheDocument()      // atmosphere
    expect(within(variantA).getByText("0.12")).toBeInTheDocument()      // cut_alignment_error
    expect(within(variantA).getByText("0.18")).toBeInTheDocument()      // unreadable_rate 0.182
    expect(within(variantA).queryByText("결과 없음")).not.toBeInTheDocument()
  })

  it("shows the not-measured placeholder only for metrics genuinely not measured", async () => {
    // Absence is expressed by OMITTING the key, never by 0.0 — a defaulted
    // unreadable_rate of 0.0 would read as "no unreadable frames" for a run nobody
    // looked at. Most runs have no visual pass, so those two rows show "—".
    const noVisual = baseRun({
      id: "run-a",
      prompt_variant: "A",
      ab_result: {
        winner: "tie",
        axis_scores: { A: { atmosphere: 4.0 }, B: { atmosphere: 4.0 } },
        rule_based_scores: {
          A: { scene_count_match_rate: 1, motion_archetype_coverage: 1 },
          B: { scene_count_match_rate: 1, motion_archetype_coverage: 1 },
        },
      },
    })
    mockFetch({ run: noVisual, runs: [noVisual, runB] })
    render(<RunAbComparisonPage runId="run-a" />)

    const variantA = await screen.findByRole("region", { name: "Variant A" })
    // 6 of the 8 rule rows + 2 unset axes are unmeasured here; the 2 supplied rule
    // metrics still show numbers.
    expect(within(variantA).getAllByText("결과 없음").length).toBeGreaterThan(0)
    expect(within(variantA).getByText("4")).toBeInTheDocument()   // atmosphere 4.0
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
