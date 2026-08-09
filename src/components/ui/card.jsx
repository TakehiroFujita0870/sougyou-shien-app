export function Card({ as: Component = 'div', children, className = '', ...props }) {
  return <Component className={`rounded-xl border border-stone-200 bg-white text-stone-900 shadow-sm ${className}`} {...props}>{children}</Component>;
}
