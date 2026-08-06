import { describe, it, expect, vi, afterEach } from "vitest"
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react"
import { ArtifactPanel } from "./ArtifactPanel"
import type { GateState, StageName } from "@/lib/types"
import type { StageArtifacts } from "@/lib/api"

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const NOT_REACHED = "아직 실행되지 않은 스테이지입니다."

function renderPanel({
  data,
  stage = data?.stage ?? "scenario",
  gateState = "n/a",
  onOpenImage = () => {},
  onGateStateChange = () => {},
  onRetryStart = () => {},
  onDirtyChange,
}: {
  data: StageArtifacts | null
  stage?: StageName
  gateState?: GateState
  onOpenImage?: (index: number) => void
  onGateStateChange?: (stage: StageName, gateState: GateState) => void
  onRetryStart?: (stage: StageName) => void
  onDirtyChange?: (dirty: boolean) => void
}) {
  return render(
    <ArtifactPanel
      runId="r1"
      stage={stage}
      data={data}
      gateState={gateState}
      onOpenImage={onOpenImage}
      onGateStateChange={onGateStateChange}
      onRetryStart={onRetryStart}
      onDirtyChange={onDirtyChange}
    />,
  )
}

describe("ArtifactPanel", () => {
  it("null data renders the not-reached empty state (AC8)", () => {
    renderPanel({ data: null })
    expect(screen.getByText(NOT_REACHED)).toBeInTheDocument()
  })

  it("scenario: Korean prose at ~65ch / 1.6 line-height (AC2)", () => {
    renderPanel({
      data: { stage: "scenario", scenes: [{ scene_num: 1, narration: "첫 번째" }, { scene_num: 2, narration: "두 번째" }] },
    })
    const prose = screen.getByText(/첫 번째/)
    expect(prose.textContent).toContain("두 번째")
    expect(prose).toHaveClass("leading-[1.6]")
    expect(prose.style.maxWidth).toBe("65ch")
  })

  it("image: 2-col grid, count label, click opens lightbox (AC3)", () => {
    const onOpenImage = vi.fn()
    renderPanel(
      {
        data: {
          stage: "image",
          images: [
            { scene_num: 1, shot_id: "s1", image_path: "workspace/r1/images/a.png", layered_fallback: false },
            { scene_num: 2, shot_id: "s2", image_path: "workspace/r1/images/b.png", layered_fallback: false },
          ],
        },
        onOpenImage,
      },
    )
    expect(screen.getByText("이미지 2개")).toBeInTheDocument()
    const imgs = screen.getAllByRole("img")
    expect(imgs[0]).toHaveAttribute("src", "/files/r1/images/a.png")
    fireEvent.click(imgs[1].closest("button")!)
    expect(onOpenImage).toHaveBeenCalledWith(1)
  })

  it("image: shows a flat-fallback warning indicator on degraded shots (Story 5.11)", () => {
    renderPanel({
      data: {
        stage: "image",
        images: [
          { scene_num: 1, shot_id: "s1", image_path: "workspace/r1/images/a.png", layered_fallback: false },
          { scene_num: 2, shot_id: "s2", image_path: "workspace/r1/images/b.png", layered_fallback: true },
        ],
      },
    })
    expect(screen.getByText("⚠ 플랫 폴백")).toBeInTheDocument()
  })

  it("tts: sorted native audio controls with scene index + duration (AC5)", () => {
    renderPanel({
      data: {
          stage: "tts",
          audio: [
            { scene_num: 2, audio_path: "workspace/r1/audio/2.wav", duration_sec: 3.5 },
            { scene_num: 1, audio_path: "workspace/r1/audio/1.wav", duration_sec: null },
          ],
        },
    })
    const players = document.querySelectorAll("audio[controls]")
    expect(players).toHaveLength(2)
    // sorted by scene_num asc: scene 1 first
    expect(players[0].getAttribute("src")).toBe("/files/r1/audio/1.wav")
    expect(screen.getByText("씬 1")).toBeInTheDocument()
    expect(screen.getByText(/3.5/)).toBeInTheDocument()
  })

  it("subtitle: monospace SRT text + cue count label (AC6)", async () => {
    const srt = "1\n00:00:00,000 --> 00:00:01,000\n안녕\n\n2\n00:00:01,000 --> 00:00:02,000\n반가워\n"
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, text: async () => srt }))
    renderPanel({ data: { stage: "subtitle", subtitles: [{ scene_num: 1, subtitle_path: "workspace/r1/subs/1.srt" }] } })
    await waitFor(() => expect(screen.getByText(/안녕/)).toBeInTheDocument())
    const block = screen.getByText(/안녕/)
    expect(block).toHaveClass("font-mono")
    expect(screen.getByText("자막 2개")).toBeInTheDocument()
  })

  it("subtitle: counts ASS Dialogue events, not SRT arrows (D14)", async () => {
    const ass = [
      "[Script Info]",
      "ScriptType: v4.00+",
      "[Events]",
      "Format: Layer, Start, End, Style, Text",
      "Dialogue: 0,0:00:00.00,0:00:01.00,Default,안녕",
      "Dialogue: 0,0:00:01.00,0:00:02.00,Default,반가워",
      "Dialogue: 0,0:00:02.00,0:00:03.00,Default,잘가",
    ].join("\n")
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, text: async () => ass }))
    renderPanel({ data: { stage: "subtitle", subtitles: [{ scene_num: 1, subtitle_path: "workspace/r1/subs/1.ass" }] } })
    await waitFor(() => expect(screen.getByText("자막 3개")).toBeInTheDocument())
  })

  it("subtitle: a Dialogue line's own text containing '-->' is not double-counted (review fix)", async () => {
    const ass = [
      "[Events]",
      "Dialogue: 0,0:00:00.00,0:00:01.00,Default,go --> there",
      "Dialogue: 0,0:00:01.00,0:00:02.00,Default,반가워",
    ].join("\n")
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, text: async () => ass }))
    renderPanel({ data: { stage: "subtitle", subtitles: [{ scene_num: 1, subtitle_path: "workspace/r1/subs/1.ass" }] } })
    await waitFor(() => expect(screen.getByText("자막 2개")).toBeInTheDocument())
  })

  it("video: full-width native player + download link (AC7)", () => {
    renderPanel({ data: { stage: "video", video_path: "workspace/r1/video.mp4" } })
    const video = document.querySelector("video[controls]")
    expect(video).toBeTruthy()
    expect(video).toHaveClass("w-full")
    expect(video!.getAttribute("src")).toBe("/files/r1/video.mp4")
    const link = screen.getByRole("link", { name: /다운로드/ })
    expect(link).toHaveAttribute("href", "/runs/r1/artifact")
  })

  it("gate controls render for pending state, disable during approve, then show success state", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 202, text: async () => "" })
    vi.stubGlobal("fetch", fetchMock)
    const onGateStateChange = vi.fn()
    renderPanel({
      data: { stage: "scenario", scenes: [{ scene_num: 1, narration: "초안" }] },
      gateState: "pending",
      onGateStateChange,
    })

    const approve = screen.getByRole("button", { name: /승인/ })
    const reject = screen.getByRole("button", { name: /반려/ })
    fireEvent.click(approve)
    expect(approve).toBeDisabled()
    expect(reject).toBeDisabled()
    await waitFor(() => expect(onGateStateChange).toHaveBeenCalledWith("scenario", "approved"))
    expect(fetchMock).toHaveBeenCalledWith(
      "/runs/r1/stages/scenario/gate",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "approve" }) }),
    )
  })

  it("gate API failure re-enables controls with inline error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "이미 처리된 게이트입니다" }),
    }))
    renderPanel({
      data: { stage: "scenario", scenes: [{ scene_num: 1, narration: "초안" }] },
      gateState: "pending",
    })
    fireEvent.click(screen.getByRole("button", { name: /반려/ }))
    await waitFor(() => expect(screen.getByText("이미 처리된 게이트입니다")).toBeInTheDocument())
    expect(screen.getByRole("button", { name: /승인/ })).not.toBeDisabled()
  })

  it("retry confirmation uses role alert, cancel hides it, and idle timer dismisses it", async () => {
    vi.useFakeTimers()
    renderPanel({
      data: { stage: "scenario", scenes: [{ scene_num: 1, narration: "초안" }] },
      gateState: "approved",
    })
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "재시도" }))
    })
    expect(screen.getByRole("alert")).toHaveTextContent("이 스테이지를 다시 실행합니까?")
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "취소" }))
    })
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "재시도" }))
    })
    await act(async () => {
      vi.runOnlyPendingTimers()
    })
    vi.useRealTimers()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("retry confirm calls the endpoint and resets stage to running", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 202, text: async () => "" })
    vi.stubGlobal("fetch", fetchMock)
    const onRetryStart = vi.fn()
    renderPanel({
      data: { stage: "scenario", scenes: [{ scene_num: 1, narration: "초안" }] },
      gateState: "rejected",
      onRetryStart,
    })
    fireEvent.click(screen.getByRole("button", { name: "재시도" }))
    fireEvent.click(screen.getByRole("button", { name: "확인" }))
    await waitFor(() => expect(onRetryStart).toHaveBeenCalledWith("scenario"))
    expect(fetchMock).toHaveBeenCalledWith("/runs/r1/stages/scenario/retry", expect.objectContaining({ method: "POST" }))
  })

  it("scenario edit mode patches text and cancel reverts without saving", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify({ text: "수정본" }) })
    vi.stubGlobal("fetch", fetchMock)
    const onDirtyChange = vi.fn()
    renderPanel({
      data: { stage: "scenario", scenes: [{ scene_num: 1, narration: "초안" }] },
      onDirtyChange,
    })
    fireEvent.click(screen.getByRole("button", { name: "편집" }))
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "버릴 변경" } })
    fireEvent.click(screen.getByRole("button", { name: "취소" }))
    expect(screen.getByText("초안")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "편집" }))
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "수정본" } })
    expect(onDirtyChange).toHaveBeenCalledWith(true)
    fireEvent.click(screen.getByRole("button", { name: "저장" }))
    await waitFor(() => expect(screen.getByText("수정본")).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledWith(
      "/runs/r1/stages/scenario/artifact",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ body: "수정본" }) }),
    )
  })

  // ── Story 12.3: pass-2 verdict warning at the scenario gate (AC7, AC8) ─────

  const QUALITY = {
    final_pass_index: 2,
    retry_scope: "scene",
    review_overall_pass: false,
    critic_verdict: "retry",
    critic_feedback: "장면 2의 긴장이 풀립니다",
    rule_metrics: {
      aggregate: { character_count: 120, sentence_count: 8, duplicate_sentence_count: 1, repeated_4gram_count: 1 },
      scenes: [{ scene_num: 1, character_count: 120, sentence_count: 8, duplicate_sentence_count: 1, repeated_4gram_count: 1 }],
      repeated_ngrams: [{ phrase: "가 나 다 라", count: 3 }],
      slop_phrase_hits: [{ scene_num: 2, phrase: "충격적인 사실", count: 2 }],
      slop_vocabulary_version: 1,
    },
    grounded_contradictions: [{
      scene_num: 3,
      narration_quote: "개체는 파란 눈을 가지고 있습니다",
      grounding_source: "entity_sheet",
      grounding_quote: "눈은 검은색이다",
      explanation: "눈 색이 접지 자료와 반대다",
      correction: "개체는 검은 눈을 가지고 있습니다",
    }],
    review_issues: [{ scene_num: 2, type: "missing_fact", severity: "warning", description: "사망자 수 누락", correction: "14명을 명시" }],
    warning: { code: "unresolved_pass2", message: "재검토 후에도 품질 문제가 남아 있습니다." },
  }

  const scenarioData = (quality?: unknown) => ({
    stage: "scenario" as const,
    scenes: [{ scene_num: 1, narration: "초안" }],
    ...(quality === undefined ? {} : { scenario_quality: quality }),
  })

  it("renders the pass-2 warning above the gate controls with icon + semantic alert (AC7)", () => {
    renderPanel({ data: scenarioData(QUALITY) as StageArtifacts, gateState: "pending" })

    const alert = screen.getByRole("alert")
    expect(alert).toHaveAttribute("aria-live", "polite")
    // Icon AND text, not colour alone.
    expect(alert.textContent).toContain("⚠")
    expect(screen.getByRole("heading", { name: /2차 검토 경고/ })).toBeInTheDocument()
    expect(alert.textContent).toContain("재검토 후에도 품질 문제가 남아 있습니다.")

    // Above the decision, not below it.
    const approve = screen.getByRole("button", { name: /승인/ })
    expect(alert.compareDocumentPosition(approve) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("warning shows the critic summary, scene evidence and code metrics (AC7)", () => {
    renderPanel({ data: scenarioData(QUALITY) as StageArtifacts, gateState: "pending" })
    const alert = screen.getByRole("alert")
    expect(alert.textContent).toContain("장면 2의 긴장이 풀립니다")
    expect(alert.textContent).toContain("씬 3")
    expect(alert.textContent).toContain("개체는 파란 눈을 가지고 있습니다")
    expect(alert.textContent).toContain("눈은 검은색이다")
    expect(alert.textContent).toContain("entity_sheet")
    expect(alert.textContent).toContain("사망자 수 누락")
    expect(alert.textContent).toContain("가 나 다 라")
    expect(alert.textContent).toContain("충격적인 사실")
    expect(alert.textContent).toContain("critic retry")
  })

  it("labels the warning as generation-time review evidence (AC8)", () => {
    renderPanel({ data: scenarioData(QUALITY) as StageArtifacts, gateState: "pending" })
    expect(screen.getByRole("alert").textContent).toContain("이후 직접 수정한 내용은 재검토되지 않았습니다")
  })

  it("warning survives an inline narration edit — review did not rerun (AC8)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => JSON.stringify({ text: "수정본" }) })
    vi.stubGlobal("fetch", fetchMock)
    renderPanel({ data: scenarioData(QUALITY) as StageArtifacts, gateState: "pending" })

    fireEvent.click(screen.getByRole("button", { name: "편집" }))
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "수정본" } })
    fireEvent.click(screen.getByRole("button", { name: "저장" }))
    await waitFor(() => expect(screen.getByText("수정본")).toBeInTheDocument())

    expect(screen.getByRole("heading", { name: /2차 검토 경고/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /승인/ })).toBeInTheDocument()
  })

  it("a clean run renders no warning (AC3)", () => {
    const clean = { ...QUALITY, final_pass_index: 1, retry_scope: "none", review_overall_pass: true, critic_verdict: "pass", grounded_contradictions: [] }
    delete (clean as { warning?: unknown }).warning
    renderPanel({ data: scenarioData(clean) as StageArtifacts, gateState: "pending" })
    expect(screen.queryByRole("heading", { name: /2차 검토 경고/ })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: /승인/ })).toBeInTheDocument()
  })

  it.each([["absent (pre-12.3 checkpoint)", undefined], ["null (cleared by retry)", null]])(
    "scenario_quality %s renders no warning and does not crash",
    (_label, quality) => {
      renderPanel({ data: scenarioData(quality) as StageArtifacts, gateState: "pending" })
      expect(screen.queryByRole("heading", { name: /2차 검토 경고/ })).not.toBeInTheDocument()
      expect(screen.getByText("초안")).toBeInTheDocument()
    },
  )

  it("warning stays visible after the gate is decided (retry decisions need it too)", () => {
    renderPanel({ data: scenarioData(QUALITY) as StageArtifacts, gateState: "approved" })
    expect(screen.getByRole("heading", { name: /2차 검토 경고/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "재시도" })).toBeInTheDocument()
  })

  it("a non-scenario stage never renders the warning block", () => {
    renderPanel({
      data: { stage: "tts", audio: [{ scene_num: 1, audio_path: "workspace/r1/a.wav", duration_sec: 1 }] },
      gateState: "pending",
    })
    expect(screen.queryByRole("heading", { name: /2차 검토 경고/ })).not.toBeInTheDocument()
  })

  // The decision itself, taken with the warning on screen (AC2, AC7). The tests
  // above prove the buttons EXIST next to a warning; these drive them, because
  // "the human can still approve or reject normally" is the acceptance criterion
  // and the warning block sits inside the same gate footer's subtree.
  it.each([
    ["approve", "승인", "approved"],
    ["reject", "반려", "rejected"],
  ])("the operator can still %s at a warned gate", async (action, label, nextState) => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 202, text: async () => "" })
    vi.stubGlobal("fetch", fetchMock)
    const onGateStateChange = vi.fn()
    renderPanel({ data: scenarioData(QUALITY) as StageArtifacts, gateState: "pending", onGateStateChange })

    fireEvent.click(screen.getByRole("button", { name: label }))

    await waitFor(() => expect(onGateStateChange).toHaveBeenCalledWith("scenario", nextState))
    expect(fetchMock).toHaveBeenCalledWith(
      "/runs/r1/stages/scenario/gate",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action }) }),
    )
    // The evidence stays on screen after the call — it is the record of what was approved.
    expect(screen.getByRole("heading", { name: /2차 검토 경고/ })).toBeInTheDocument()
  })

  it("the retry confirmation is announced without swallowing the warning alert (AC7)", async () => {
    renderPanel({ data: scenarioData(QUALITY) as StageArtifacts, gateState: "approved" })
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "재시도" }))
    })

    // Two live regions now: the standing warning and the confirmation. Neither
    // replaces the other — a single-alert assumption anywhere here would mean the
    // operator loses the reason they were retrying mid-confirmation.
    const alerts = screen.getAllByRole("alert")
    expect(alerts.some((a) => a.textContent?.includes("이 스테이지를 다시 실행합니까?"))).toBe(true)
    expect(alerts.some((a) => a.textContent?.includes("재검토 후에도 품질 문제가 남아 있습니다."))).toBe(true)
  })
})
