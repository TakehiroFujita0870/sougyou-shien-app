import { cn } from '../../lib/utils';

export function Field({ label, hint, className, children, ...props }) {
  return <label className={cn('grid gap-2 text-sm font-bold text-[var(--color-text)]', className)} {...props}><span>{label}</span>{children}{hint && <span className="font-normal text-[var(--color-text-muted)]">{hint}</span>}</label>;
}
