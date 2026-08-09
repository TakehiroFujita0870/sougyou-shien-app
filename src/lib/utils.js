import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

// Matches the utility used by shadcn/ui so component variants remain
// composable without conflicting Tailwind classes.
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
