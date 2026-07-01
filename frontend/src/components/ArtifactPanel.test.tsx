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
            { scene_num: 1, shot_id: "s1", image_path: "workspace/r1/images/a.png" },
            { scene_num: 2, shot_id: "s2", image_path: "workspace/r1/images/b.png" },
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
})
