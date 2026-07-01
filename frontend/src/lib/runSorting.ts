import type { Run } from "@/lib/types"

// AC1/UX-DR7: awaiting_approval runs float to the top; within each group, newest
// (started_at desc) first. Pure + stable so it is unit-testable on its own.
export function sortRuns(runs: Run[]): Run[] {
  return [...runs].sort((a, b) => {
    const aWait = a.status === "awaiting_approval" ? 0 : 1
    const bWait = b.status === "awaiting_approval" ? 0 : 1
    if (aWait !== bWait) return aWait - bWait
    return b.started_at.localeCompare(a.started_at) // ISO-8601 strings sort lexically
  })
}
