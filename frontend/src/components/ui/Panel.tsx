import type { ReactNode } from 'react'
import { cn } from '@/utils/cn'

export function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={cn('rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)]', className)}
    >
      {children}
    </section>
  )
}

export function PanelHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--border)] px-5 py-4">
      <div>
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {description ? <p className="mt-1 text-sm text-[var(--fg-muted)]">{description}</p> : null}
      </div>
      {action}
    </div>
  )
}
