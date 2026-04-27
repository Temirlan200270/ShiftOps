import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * `cn` follows the shadcn/ui convention: clsx for conditional class
 * composition, tailwind-merge to dedupe conflicting utilities. We keep the
 * helper local rather than depending on the shadcn CLI so the project has
 * zero generated code that we don't fully understand.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
