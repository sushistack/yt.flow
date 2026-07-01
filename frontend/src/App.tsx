import { usePathname } from "@/lib/navigate"
import { Dashboard } from "@/pages/Dashboard"
import { RunDetail } from "@/pages/RunDetail"

// Client-side routing (Story 3.4): /runs/{id} → Run Detail, everything else →
// Dashboard. Tolerant of the /app base prefix the SPA is served under.
export default function App() {
  const pathname = usePathname()
  const match = pathname.match(/\/runs\/([^/?#]+)/)
  return match ? <RunDetail runId={match[1]} /> : <Dashboard />
}
