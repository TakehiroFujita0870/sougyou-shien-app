import { cn } from '../../lib/utils';

const variants = {
  primary: 'bg-[var(--color-primary)] text-[var(--color-primary-foreground)] hover:bg-[var(--color-primary-hover)]',
  secondary: 'border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text)] hover:bg-[var(--color-muted)]',
  ghost: 'text-[var(--color-text-muted)] hover:bg-[var(--color-muted)] hover:text-[var(--color-text)]',
};

export function Button({ className, variant = 'primary', ...props }) {
  return <button className={cn('inline-flex min-h-11 items-center justify-center rounded-xl px-4 py-2 text-sm font-bold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)] disabled:cursor-not-allowed disabled:opacity-60', variants[variant], className)} {...props} />;
}
