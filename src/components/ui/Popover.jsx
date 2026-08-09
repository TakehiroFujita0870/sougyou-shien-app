import * as PopoverPrimitive from '@radix-ui/react-popover';
import { cn } from '../../lib/utils';

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;

export function PopoverContent({ className, align = 'start', sideOffset = 8, ...props }) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        className={cn('z-50 min-w-56 rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] p-2 text-[var(--color-text)] shadow-xl outline-none', className)}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
}
