import { cn } from '../../lib/utils';

export function Card({ className, ...props }) {
  return <div className={cn('rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text)] shadow-sm', className)} {...props} />;
}
