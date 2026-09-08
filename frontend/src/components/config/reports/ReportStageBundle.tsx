import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import type { Report } from '@/types'
import { ReportListRow } from './ReportListRow'
import { ReportStageHeader } from './ReportStageHeader'
import { cn } from '@/utils/cn'
import type { StageBundleModel } from './utils'

type Props = {
  bundle: StageBundleModel
  expanded: boolean
  onToggle: () => void
  onOpenReport: (report: Report) => void
  onToggleEnabled: (report: Report) => void
  busy?: boolean
}

export function ReportStageBundle({
  bundle,
  expanded,
  onToggle,
  onOpenReport,
  onToggleEnabled,
  busy,
}: Props) {
  return (
    <section
      className={cn(
        'group rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] shadow-sm shadow-black/5 dark:shadow-black/30',
        expanded && 'border-l-[3px] border-l-[var(--accent)]',
      )}
    >
      <ReportStageHeader bundle={bundle} expanded={expanded} onToggle={onToggle} />
      <div
        id={`stage-panel-${bundle.key}`}
        role="region"
        aria-labelledby={`stage-header-${bundle.key}`}
        hidden={!expanded}
      >
        {bundle.reports.length === 0 ? (
          <div className="flex flex-col items-start gap-3 px-5 py-6 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-[var(--fg-muted)]">No reports configured for this stage yet.</p>
            <Link to="/developer/add-report">
              <Button variant="secondary">Create report in this stage</Button>
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)] px-2 py-1 sm:px-3">
            {bundle.reports.map((report) => (
              <ReportListRow
                key={report.code}
                report={report}
                onOpen={onOpenReport}
                onToggleEnabled={onToggleEnabled}
                busy={busy}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
