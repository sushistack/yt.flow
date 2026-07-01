import { describe, expect, it } from "vitest"
import { filterScps, sortScpsByRating } from "@/lib/scpSearch"
import type { ScpEntry } from "@/lib/types"

const scp = (id: string, nickname: string, rating: number, tags?: string[]): ScpEntry => ({
  id,
  nickname,
  object_class: "Euclid",
  rating,
  tags,
})

const DATA = [
  scp("SCP-096", "The Shy Guy", 4.8, ["shy-guy", "featured", "scp"]),
  scp("SCP-049", "Plague Doctor", 4.5, ["plague doctor"]),
  scp("SCP-173", "The Sculpture", 4.9),
]

describe("filterScps", () => {
  it("matches numeric ID", () => {
    expect(filterScps(DATA, "096").map((s) => s.id)).toEqual(["SCP-096"])
  })

  it("matches full ID", () => {
    expect(filterScps(DATA, "SCP-096").map((s) => s.id)).toEqual(["SCP-096"])
  })

  it("matches nickname with hyphen/space normalization", () => {
    expect(filterScps(DATA, "shy guy").map((s) => s.id)).toEqual(["SCP-096"])
    expect(filterScps(DATA, "plague-doctor").map((s) => s.id)).toEqual(["SCP-049"])
  })

  it("excludes meta/admin tags from matching", () => {
    // "featured" and "scp" are meta tags on SCP-096 — must not match.
    expect(filterScps(DATA, "featured")).toEqual([])
  })

  it("returns all rows for an empty query, preserving order", () => {
    expect(filterScps(DATA, "").map((s) => s.id)).toEqual(["SCP-096", "SCP-049", "SCP-173"])
  })
})

describe("sortScpsByRating", () => {
  it("sorts by rating desc", () => {
    expect(sortScpsByRating(DATA).map((s) => s.id)).toEqual(["SCP-173", "SCP-096", "SCP-049"])
  })
})
