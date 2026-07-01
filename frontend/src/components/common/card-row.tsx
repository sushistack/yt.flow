import { cn } from "@/lib/utils"

export type CardRowProps = {
  children: React.ReactNode
  className?: string
  onClick?: () => void
  disabled?: boolean
}

// Full-row navigation target (EXPERIENCE.md). No nested action buttons here —
// row actions belong to Story 3.3. Renders a <button> when interactive so it is
// focusable and keyboard-operable; a plain <div> otherwise.
export function CardRow({ children, className, onClick, disabled }: CardRowProps) {
  const base = cn(
    "block w-full border-b border-border bg-card px-4 py-3 text-left transition-colors",
    !disabled && "hover:bg-card-hover",
    disabled && "opacity-50",
    className,
  )

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          base,
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed",
        )}
      >
        {children}
      </button>
    )
  }

  return <div className={base}>{children}</div>
}
