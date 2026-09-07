import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useReports, useStages } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { formatStageLabel } from '@/utils/cn'

type FilterMode = 'all' | 'standard' | 'requirement' | 'utilities'

const STAGE_FILTERS: Record<FilterMode, (stage: string) => boolean> = {
  all: () => true,
  standard: (s) =>
    s.includes('common') || s.includes('helper') || s === 'retail' || s === 'finance',
  requirement: (s) => s.includes('requirement') || s.includes('atros'),
  utilities: (s) => s.includes('utility'),
}

export function ReportsPage({ mode = 'all' }: { mode?: FilterMode }) {
  const [stageFilter, setStageFilter] = useState('all')
  const reports = useReports({ enabledOnly: false })
  const stages = useStages()

  const filtered = useMemo(() => {
    return (reports.data ?? []).filter((r) => {
      if (!STAGE_FILTERS[mode](r.stage)) return false
      if (stageFilter !== 'all' && r.stage !== stageFilter) return false
      return true
    })
  }, [reports.data, mode, stageFilter])

  if (reports.isLoading) return <Spinner label="Loading reports…" />
  if (reports.error) {
    return (
      <ErrorState
        title="Unable to load reports"
        message={
          reports.error instanceof Error
            ? reports.error.message
            : 'Configuration file could not be parsed.'
        }
        onRetry={() => void reports.refetch()}
      />
    )
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant={stageFilter === 'all' ? 'primary' : 'secondary'}
          onClick={() => setStageFilter('all')}
        >
          All stages
        </Button>
        {(stages.data ?? []).map((s) => (
          <Button
            key={s.key}
            variant={stageFilter === s.key ? 'primary' : 'ghost'}
            onClick={() => setStageFilter(s.key)}
          >
            {formatStageLabel(s.label)}
          </Button>
        ))}
      </div>

      <Panel>
        <PanelHeader
          title={`${filtered.length} reports`}
          description="Modules resolved from report.yaml via the Phase 1 API"
          action={
            <Link to="/pipeline/run">
              <Button variant="secondary">Run Pipeline</Button>
            </Link>
          }
        />
        {filtered.length === 0 ? (
          <EmptyState title="No reports match this filter" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">
                <tr>
                  <th className="px-5 py-3 font-medium">Report</th>
                  <th className="px-5 py-3 font-medium">Stage</th>
                  <th className="px-5 py-3 font-medium">Clients</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Module</th>
                  <th className="px-5 py-3 font-medium">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filtered.map((r) => (
                  <tr key={r.code} className="hover:bg-[var(--accent-soft)]/40">
                    <td className="px-5 py-3">
                      <p className="font-medium">{r.label}</p>
                      <p className="font-mono text-xs text-[var(--fg-muted)]">{r.code}</p>
                    </td>
                    <td className="px-5 py-3 font-mono text-xs">{r.stage}</td>
                    <td className="px-5 py-3 text-xs">
                      {r.clients?.length ? r.clients.join(', ') : 'All'}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-1">
                        <Badge tone={r.enabled ? 'ok' : 'warn'}>
                          {r.enabled ? 'enabled' : 'disabled'}
                        </Badge>
                        <Badge tone={r.module_file_exists ? 'accent' : 'danger'}>
                          {r.module_file_exists ? 'file' : 'missing'}
                        </Badge>
                      </div>
                    </td>
                    <td className="max-w-[220px] truncate px-5 py-3 font-mono text-[11px] text-[var(--fg-muted)]">
                      {r.module}
                    </td>
                    <td className="px-5 py-3">
                      <Link
                        to="/pipeline/run"
                        state={{
                          reports: [r.code],
                          clients: r.clients?.length ? r.clients : undefined,
                        }}
                      >
                        <Button variant="secondary" disabled={!r.enabled}>
                          Run
                        </Button>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
