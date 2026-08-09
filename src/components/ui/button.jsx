export function Button({ children, className = '', ...props }) {
  return <button className={`inline-flex min-h-11 items-center justify-center rounded-md bg-stone-900 px-5 py-2 text-sm font-bold text-white transition-colors hover:bg-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2 ${className}`} {...props}>{children}</button>;
}
