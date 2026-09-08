import { cn } from '@/utils/cn'
import type { Report } from '@/types'
import { reportAttention } from './utils'

export function ReportStatusBadge({ report }: { report: Report }) {
  const attention = reportAttention(report)
  const label = attention === 'paused' ? 'Paused' : attention === 'attention' ? 'Attention' : 'Active'
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold tracking-wide',
        attention === 'ok' && 'bg-emerald-500/10 text-[#16A34A]',
        attention === 'paused' && 'bg-amber-500/10 text-[#D97706]',
        attention === 'attention' && 'bg-red-500/10 text-[#DC2626]',
      )}
    >
      {label}
    </span>
  )
}

export function ReportHealthDot({ report }: { report: Report }) {
  const attention = reportAttention(report)
  const title =
    attention === 'ok'
      ? 'Module healthy'
      : attention === 'paused'
        ? 'Report paused'
        : !report.module_file_exists
          ? 'Module file missing'
          : 'Module not importable'
  return (
    <span
      title={title}
      aria-label={title}
      className={cn(
        'mt-1.5 h-2 w-2 shrink-0 rounded-full',
        attention === 'ok' && 'bg-[#16A34A]',
        attention === 'paused' && 'bg-[#D97706]',
        attention === 'attention' && 'bg-[#DC2626]',
      )}
    />
  )
}
