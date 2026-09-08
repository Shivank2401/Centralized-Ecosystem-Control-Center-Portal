import { cn } from '@/utils/cn'

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: React.ReactNode
  tone?: 'neutral' | 'ok' | 'warn' | 'danger' | 'accent'
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-2 py-0.5 font-mono text-[11px] font-medium tracking-wide uppercase',
        tone === 'neutral' && 'bg-[var(--accent-soft)] text-[var(--fg-muted)]',
        tone === 'ok' && 'bg-emerald-500/15 text-[var(--color-ok)]',
        tone === 'warn' && 'bg-amber-500/15 text-[var(--color-warn)]',
        tone === 'danger' && 'bg-red-500/15 text-[var(--color-danger)]',
        tone === 'accent' &&
          'border border-[var(--border)] bg-white text-[var(--accent)] dark:border-transparent',
      )}
    >
      {children}
    </span>
  )
}
