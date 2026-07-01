import { describe, it, expect, vi, afterEach } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { ArtifactPanel } from "./ArtifactPanel"

afterEach(() => vi.restoreAllMocks())

const NOT_REACHED = "아직 실행되지 않은 스테이지입니다."

describe("ArtifactPanel", () => {
  it("null data renders the not-reached empty state (AC8)", () => {
    render(<ArtifactPanel runId="r1" data={null} onOpenImage={() => {}} />)
    expect(screen.getByText(NOT_REACHED)).toBeInTheDocument()
  })

  it("undefined data renders a distinct loading state", () => {
    render(<ArtifactPanel runId="r1" data={undefined} onOpenImage={() => {}} />)
    expect(screen.getByText("불러오는 중...")).toBeInTheDocument()
    expect(screen.queryByText(NOT_REACHED)).not.toBeInTheDocument()
  })

  it("scenario: Korean prose at ~65ch / 1.6 line-height (AC2)", () => {
    render(
      <ArtifactPanel
        runId="r1"
        data={{ stage: "scenario", scenes: [{ scene_num: 1, narration: "첫 번째" }, { scene_num: 2, narration: "두 번째" }] }}
        onOpenImage={() => {}}
      />,
    )
    const prose = screen.getByText(/첫 번째/)
    expect(prose.textContent).toContain("두 번째")
    expect(prose).toHaveClass("leading-[1.6]")
    expect(prose.style.maxWidth).toBe("65ch")
  })

  it("image: 2-col grid, count label, click opens lightbox (AC3)", () => {
    const onOpenImage = vi.fn()
    render(
      <ArtifactPanel
        runId="r1"
        data={{
          stage: "image",
          images: [
            { scene_num: 2, shot_id: "s2", image_path: "workspace/r1/images/b.png" },
            { scene_num: 1, shot_id: "s1", image_path: "workspace/r1/images/a.png" },
          ],
        }}
        onOpenImage={onOpenImage}
      />,
    )
    expect(screen.getByText("이미지 2개")).toBeInTheDocument()
    const imgs = screen.getAllByRole("img")
    expect(imgs[0]).toHaveAttribute("src", "/files/r1/images/a.png")
    fireEvent.click(imgs[1].closest("button")!)
    expect(onOpenImage).toHaveBeenCalledWith(1)
  })

  it("tts: sorted native audio controls with scene index + duration (AC5)", () => {
    render(
      <ArtifactPanel
        runId="r1"
        data={{
          stage: "tts",
          audio: [
            { scene_num: 2, audio_path: "workspace/r1/audio/2.wav", duration_sec: 3.5 },
            { scene_num: 1, audio_path: "workspace/r1/audio/1.wav", duration_sec: null },
          ],
        }}
        onOpenImage={() => {}}
      />,
    )
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
    render(
      <ArtifactPanel
        runId="r1"
        data={{ stage: "subtitle", subtitles: [{ scene_num: 1, subtitle_path: "workspace/r1/subs/1.srt" }] }}
        onOpenImage={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByText(/안녕/)).toBeInTheDocument())
    const block = screen.getByText(/안녕/)
    expect(block).toHaveClass("font-mono")
    expect(screen.getByText("자막 2개")).toBeInTheDocument()
  })

  it("video: full-width native player + download link (AC7)", () => {
    render(
      <ArtifactPanel
        runId="r1"
        data={{ stage: "video", video_path: "workspace/r1/video.mp4" }}
        onOpenImage={() => {}}
      />,
    )
    const video = document.querySelector("video[controls]")
    expect(video).toBeTruthy()
    expect(video).toHaveClass("w-full")
    expect(video!.getAttribute("src")).toBe("/files/r1/video.mp4")
    const link = screen.getByRole("link", { name: /다운로드/ })
    expect(link).toHaveAttribute("href", "/runs/r1/artifact")
  })
})
