import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

// shadcn/ui class-name helper. Present so later stories can `npx shadcn add` cleanly.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
