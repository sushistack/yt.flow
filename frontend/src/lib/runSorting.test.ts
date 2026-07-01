import { describe, expect, it } from "vitest"
import { sortRuns } from "@/lib/runSorting"
import type { Run } from "@/lib/types"

const run = (id: string, status: Run["status"], started_at: string): Run => ({
  id,
  scp_id: id,
  status,
  current_stage: null,
  gate_states: null,
  started_at,
  updated_at: started_at,
})

describe("sortRuns", () => {
  it("floats awaiting_approval to the top", () => {
    const out = sortRuns([
      run("a", "running", "2026-07-01T10:00:00Z"),
      run("b", "awaiting_approval", "2026-07-01T08:00:00Z"),
    ])
    expect(out.map((r) => r.id)).toEqual(["b", "a"])
  })

  it("sorts by started_at desc within each group", () => {
    const out = sortRuns([
      run("old-wait", "awaiting_approval", "2026-07-01T08:00:00Z"),
      run("new-wait", "awaiting_approval", "2026-07-01T09:00:00Z"),
      run("old-run", "complete", "2026-07-01T06:00:00Z"),
      run("new-run", "running", "2026-07-01T07:00:00Z"),
    ])
    expect(out.map((r) => r.id)).toEqual(["new-wait", "old-wait", "new-run", "old-run"])
  })

  it("does not mutate the input array", () => {
    const input = [run("a", "running", "2026-07-01T10:00:00Z")]
    sortRuns(input)
    expect(input).toHaveLength(1)
  })
})
