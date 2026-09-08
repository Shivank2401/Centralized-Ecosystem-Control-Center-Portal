import { ChevronDown, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from '@/utils/cn'
import type { StageBundleModel } from './utils'

type Props = {
  bundle: StageBundleModel
  expanded: boolean
  onToggle: () => void
}

export function ReportStageHeader({ bundle, expanded, onToggle }: Props) {
  const count = bundle.reports.length
  const summaryParts: string[] = []
  if (bundle.enabledCount) summaryParts.push(`${bundle.enabledCount} active`)
  if (bundle.pausedCount) summaryParts.push(`${bundle.pausedCount} paused`)
  if (bundle.attentionCount) summaryParts.push(`${bundle.attentionCount} need attention`)

  return (
    <div
      className={cn(
        'flex items-center gap-3 px-4 py-3 sm:px-5',
        expanded && 'border-b border-[var(--border)]',
      )}
    >
      <button
        type="button"
        id={`stage-header-${bundle.key}`}
        aria-expanded={expanded}
        aria-controls={`stage-panel-${bundle.key}`}
        onClick={onToggle}
        className="flex min-w-0 flex-1 items-start gap-3 rounded-md text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
      >
        <ChevronDown
          className={cn(
            'mt-0.5 h-4 w-4 shrink-0 text-[var(--fg-muted)] transition-transform duration-200',
            !expanded && '-rotate-90',
          )}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <h3 className="text-sm font-semibold tracking-tight text-[var(--fg)] uppercase sm:text-[15px]">
              {bundle.label}
            </h3>
            <span className="text-xs text-[var(--fg-muted)]">
              {count} {count === 1 ? 'report' : 'reports'}
            </span>
          </div>
          {summaryParts.length ? (
            <p className="mt-0.5 text-xs text-[var(--fg-muted)]">{summaryParts.join(' · ')}</p>
          ) : (
            <p className="mt-0.5 text-xs text-[var(--fg-muted)]">No reports in this stage</p>
          )}
        </div>
      </button>
      <Link
        to={`/developer/add-report`}
        title={`Add report to ${bundle.label}`}
        className={cn(
          'inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--accent)]',
          'opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100',
          'hover:bg-[var(--accent-soft)]',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]',
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <Plus className="h-3.5 w-3.5" />
        Add report
      </Link>
    </div>
  )
}
