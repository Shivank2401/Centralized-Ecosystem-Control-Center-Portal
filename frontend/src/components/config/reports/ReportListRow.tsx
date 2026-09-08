import { Users } from 'lucide-react'
import type { Report } from '@/types'
import { ReportActionsMenu } from './ReportActionsMenu'
import { ReportHealthDot, ReportStatusBadge } from './ReportStatusBadge'

type Props = {
  report: Report
  onOpen: (report: Report) => void
  onToggleEnabled: (report: Report) => void
  busy?: boolean
}

export function ReportListRow({ report, onOpen, onToggleEnabled, busy }: Props) {
  const clientsLabel = report.clients?.length ? report.clients.join(', ') : 'All clients'
  const clientCount = report.clients?.length ?? null
  const description =
    report.description?.trim() ||
    (report.output_subdir ? `Output · ${report.output_subdir}` : report.code)

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(report)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(report)
        }
      }}
      className="group flex cursor-pointer items-start gap-3 rounded-lg border border-transparent px-3 py-3 transition hover:border-[var(--border)] hover:bg-[var(--bg)]/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] sm:items-center"
    >
      <ReportHealthDot report={report} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className="truncate text-sm font-semibold text-[var(--fg)]">{report.label}</p>
          <ReportStatusBadge report={report} />
          {report.menu_order != null ? (
            <span className="font-mono text-[10px] text-[var(--fg-muted)]">#{report.menu_order}</span>
          ) : null}
        </div>
        <p className="mt-0.5 truncate text-xs text-[var(--fg-muted)]">{description}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--fg-muted)]">
          <span className="font-mono text-[10px]">{report.code}</span>
          <span className="inline-flex items-center gap-1">
            <Users className="h-3 w-3" aria-hidden />
            {clientCount != null ? `${clientCount} client${clientCount === 1 ? '' : 's'}` : 'All'}
            <span className="hidden sm:inline">· {clientsLabel}</span>
          </span>
          <span>On demand</span>
        </div>
      </div>
      <ReportActionsMenu
        report={report}
        onEdit={onOpen}
        onToggleEnabled={onToggleEnabled}
        busy={busy}
      />
    </div>
  )
}
