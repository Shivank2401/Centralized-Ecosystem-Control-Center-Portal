import { AlertTriangle, Inbox, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-[var(--fg-muted)]">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--accent)]" />
      <p className="text-sm">{label}</p>
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <Inbox className="h-10 w-10 text-[var(--fg-muted)] opacity-60" />
      <h3 className="text-base font-semibold">{title}</h3>
      {description ? <p className="max-w-md text-sm text-[var(--fg-muted)]">{description}</p> : null}
      {action}
    </div>
  )
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
}: {
  title?: string
  message?: string
  onRetry?: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <AlertTriangle className="h-10 w-10 text-[var(--color-danger)]" />
      <h3 className="text-base font-semibold">{title}</h3>
      {message ? <p className="max-w-md text-sm text-[var(--fg-muted)]">{message}</p> : null}
      <div className="mt-2 flex gap-2">
        {onRetry ? (
          <Button variant="secondary" onClick={onRetry}>
            <RefreshCw className="h-4 w-4" />
            Retry
          </Button>
        ) : null}
        <Link to="/developer/diagnostics">
          <Button variant="ghost">Open Diagnostics</Button>
        </Link>
      </div>
    </div>
  )
}
