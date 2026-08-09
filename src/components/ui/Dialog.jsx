import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '../../lib/utils';

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({ className, children, closeDisabled = false, ...props }) {
  return <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/35" />
    <DialogPrimitive.Content className={cn('fixed left-1/2 top-1/2 z-50 w-[min(32rem,calc(100%-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-6 shadow-2xl outline-none', closeDisabled && '[&>button.absolute.right-4.top-4]:pointer-events-none [&>button.absolute.right-4.top-4]:opacity-60', className)} {...props}>
      {children}
      <DialogPrimitive.Close disabled={closeDisabled} aria-disabled={closeDisabled || undefined} tabIndex={closeDisabled ? -1 : undefined} className="absolute right-4 top-4 grid size-9 place-items-center rounded-lg text-[var(--color-text-muted)] hover:bg-[var(--color-muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)] disabled:cursor-not-allowed disabled:opacity-60" aria-label="閉じる"><X className="size-4" aria-hidden="true" /></DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>;
}

export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;
