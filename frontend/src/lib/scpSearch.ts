import type { ScpEntry } from "@/lib/types"

// Meta/admin tags never participate in nickname matching or display (UX-DR8).
const META_TAGS = new Set([
  "_licensebox",
  "scp",
  "_cc",
  "featured",
  "illustrated",
  "rewrite",
  "co-authored",
  "audio",
])

// Lowercase and drop separators so spaces/hyphens are equivalent:
// "shy guy" == "shy-guy", "SCP-096" == "096" substring, "plague-doctor" == "plague doctor".
function normalize(s: string): string {
  return s.toLowerCase().replace(/[\s-]+/g, "")
}

function searchableText(scp: ScpEntry): string {
  const tags = (scp.tags ?? []).filter((t) => !META_TAGS.has(t.toLowerCase()))
  return normalize([scp.id, scp.nickname, ...tags].join(" "))
}

// Empty query → all SCPs in the given (rating-desc) order. Filtering preserves
// input order among matches, so callers pass a rating-desc list to keep AC ordering.
export function filterScps(scps: ScpEntry[], query: string): ScpEntry[] {
  const q = normalize(query)
  if (!q) return scps
  return scps.filter((scp) => searchableText(scp).includes(q))
}

// Rating desc; ties broken by numeric-ID asc for stable, deterministic order.
export function sortScpsByRating(scps: ScpEntry[]): ScpEntry[] {
  return [...scps].sort((a, b) => b.rating - a.rating || a.id.localeCompare(b.id))
}
