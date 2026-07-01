import { describe, it, expect, vi, afterEach } from "vitest"
import { fileUrl, parseGateStates, getStageArtifacts, getRun, ApiError } from "./api"

afterEach(() => vi.restoreAllMocks())

describe("fileUrl", () => {
  it("maps a workspace path to the /files mount regardless of prefix", () => {
    expect(fileUrl("workspace/run-1/images/scene_001.png")).toBe("/files/run-1/images/scene_001.png")
    expect(fileUrl("./workspace/run-1/audio/scene_001.wav")).toBe("/files/run-1/audio/scene_001.wav")
    expect(fileUrl("/home/u/workspace/run-1/video.mp4")).toBe("/files/run-1/video.mp4")
    expect(fileUrl("/tmp/custom-work/r1/images/scene_001.png")).toBe("/files/r1/images/scene_001.png")
    expect(fileUrl("workspace/r1/output.mp4")).toBe("/files/r1/output.mp4")
  })
})

describe("parseGateStates", () => {
  it("parses the JSON gate map, tolerating null/garbage", () => {
    expect(parseGateStates('{"image":"pending"}')).toEqual({ image: "pending" })
    expect(parseGateStates(null)).toEqual({})
    expect(parseGateStates("not json")).toEqual({})
  })
})

describe("getStageArtifacts", () => {
  it("returns null on 404 (stage not yet reached)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    expect(await getStageArtifacts("r1", "video")).toBeNull()
  })

  it("throws ApiError on non-404 failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }))
    await expect(getStageArtifacts("r1", "scenario")).rejects.toBeInstanceOf(ApiError)
  })

  it("returns the parsed artifact DTO on success", async () => {
    const dto = { stage: "scenario", scenes: [{ scene_num: 1, narration: "안녕" }] }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => dto }))
    expect(await getStageArtifacts("r1", "scenario")).toEqual(dto)
  })
})

describe("getRun", () => {
  it("fetches run detail from /runs/{id}", async () => {
    const run = { id: "r1", scp_id: "SCP-096", status: "running", current_stage: "image" }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => run })
    vi.stubGlobal("fetch", fetchMock)
    expect(await getRun("r1")).toEqual(run)
    expect(fetchMock.mock.calls[0][0]).toBe("/runs/r1")
  })
})
