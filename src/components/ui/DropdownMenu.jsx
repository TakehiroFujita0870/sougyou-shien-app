import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu';
import { cn } from '../../lib/utils';

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;
export const DropdownMenuLabel = DropdownMenuPrimitive.Label;
export const DropdownMenuSeparator = DropdownMenuPrimitive.Separator;

export function DropdownMenuContent({ className, align = 'start', sideOffset = 8, ...props }) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        className={cn('z-50 min-w-60 rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-surface-raised)] p-1.5 text-[var(--color-text)] shadow-xl outline-none', className)}
        {...props}
      />
    </DropdownMenuPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, ...props }) {
  return <DropdownMenuPrimitive.Item className={cn('relative flex min-h-10 cursor-pointer select-none items-center rounded-lg px-2.5 py-2 text-sm outline-none transition-colors focus:bg-[var(--color-muted)] data-[disabled]:pointer-events-none data-[disabled]:opacity-50', className)} {...props} />;
}
