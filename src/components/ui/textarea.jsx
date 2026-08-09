export function Textarea({ className = '', ...props }) {
  return <textarea className={`flex min-h-20 w-full resize-y rounded-md border border-stone-200 bg-transparent p-2 text-base leading-6 shadow-sm outline-none placeholder:text-stone-400 focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2 ${className}`} {...props} />;
}
