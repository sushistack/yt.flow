import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import App from "./App"
import { navigate } from "./lib/navigate"

// Minimal EventSource stub so RunDetail's SSE effect doesn't throw under jsdom.
class StubEventSource {
  addEventListener() {}
  close() {}
}

const RUN = {
  id: "r1",
  scp_id: "SCP-096",
  status: "complete",
  current_stage: "video",
  gate_states: null,
  prompt_variant: "A",
  ab_pair_id: null,
  langfuse_trace_url: null,
}

const PAIR = {
  ...RUN,
  id: "r2",
  prompt_variant: "B",
  ab_pair_id: "r1",
}

beforeEach(() => {
  vi.stubGlobal("EventSource", StubEventSource as unknown as typeof EventSource)
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url === "/runs/r1") return Promise.resolve({ ok: true, status: 200, json: async () => RUN })
      if (url === "/runs") return Promise.resolve({ ok: true, status: 200, json: async () => [RUN, PAIR] })
      if (url.includes("/stages/scenario/artifacts"))
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ stage: "scenario", scenes: [{ scene_num: 1, narration: "본문" }] }),
        })
      return Promise.resolve({ ok: false, status: 404 })
    }),
  )
})
afterEach(() => vi.restoreAllMocks())

describe("App routing", () => {
  it("renders Run Detail at /runs/{id} (AC1)", async () => {
    navigate("/runs/r1")
    render(<App />)
    await waitFor(() => expect(screen.getByRole("main")).toBeInTheDocument())
    expect(screen.getByRole("complementary")).toBeInTheDocument() // stage sidebar
    expect(screen.getByText("SCP-096")).toBeInTheDocument()
  })

  it("renders A/B Comparison at /runs/{id}/ab", async () => {
    navigate("/runs/r1/ab")
    render(<App />)
    expect(await screen.findByRole("heading", { name: "A/B 비교" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "Variant A" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "Variant B" })).toBeInTheDocument()
  })
})
