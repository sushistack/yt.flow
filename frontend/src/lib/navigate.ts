import { useSyncExternalStore } from "react"

// ponytail: History-API navigation, no router lib. Two routes (dashboard, run
// detail) don't justify a dependency. pushState doesn't fire popstate, so we
// dispatch it ourselves to notify usePathname subscribers (Story 3.4 upgrade).
export function navigate(path: string): void {
  const nextPath = withCurrentBase(path)
  if (nextPath === window.location.pathname) return
  window.history.pushState({}, "", nextPath)
  window.dispatchEvent(new PopStateEvent("popstate"))
}

function withCurrentBase(path: string): string {
  if (!path.startsWith("/") || path.startsWith("/app/") || path === "/app") return path
  return window.location.pathname.startsWith("/app") ? `/app${path}` : path
}

function subscribe(cb: () => void): () => void {
  window.addEventListener("popstate", cb)
  return () => window.removeEventListener("popstate", cb)
}

// Reactive current pathname; re-renders on navigate() and browser back/forward.
export function usePathname(): string {
  return useSyncExternalStore(
    subscribe,
    () => window.location.pathname,
    () => window.location.pathname,
  )
}
