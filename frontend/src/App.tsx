import { usePathname } from "@/lib/navigate"
import { Dashboard } from "@/pages/Dashboard"
import { RunAbComparisonPage } from "@/pages/RunAbComparisonPage"
import { RunDetail } from "@/pages/RunDetail"

// Client-side routing (Story 3.4). Story 3.7 adds /characters routes.
export default function App() {
  const pathname = usePathname()

  // /runs/{id}/ab (also under /app)
  const abMatch = pathname.match(/\/(?:app\/)?runs\/([^/?#]+)\/ab/)
  if (abMatch) return <RunAbComparisonPage runId={abMatch[1]} />

  // /characters/{id} — validate UUID to avoid matching /characters/new etc.
  const charIdMatch = pathname.match(/\/(?:app\/)?characters\/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/)
  if (charIdMatch) return <CharacterDetailPage charId={charIdMatch[1]} />

  // /characters (with or without /app/ prefix, trailing-slash tolerant)
  if (/^\/(?:app\/)?characters\/?$/.test(pathname)) {
    return <CharacterListPage />
  }

  // /runs/{id} (also under /app)
  const runMatch = pathname.match(/\/(?:app\/)?runs\/([^/?#]+)/)
  return runMatch ? <RunDetail runId={runMatch[1]} /> : <Dashboard />
}

// ── Character Pages (Story 3.7) ────────────────────────────────────────────
// ponytail: module-level imports (not React.lazy) — the SPA is small enough
// that code-splitting isn't needed; all pages load eagerly.

import { CharacterListPage } from "@/pages/CharacterListPage"
import { CharacterDetailPage } from "@/pages/CharacterDetailPage"
