import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useClients, useRuns } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { formatDuration } from '@/pages/RunDetail'
import type { PipelineRunStatus } from '@/types'

function tone(status: PipelineRunStatus) {
  if (status === 'SUCCESS') return 'ok' as const
  if (status === 'FAILED') return 'danger' as const
  if (status === 'CANCELLED') return 'warn' as const
  if (status === 'RUNNING') return 'accent' as const
  return 'neutral' as const
}

export function RunHistoryPage() {
  const clients = useClients()
  const [status, setStatus] = useState<string>('')
  const [client, setClient] = useState<string>('')
  const runs = useRuns({
    limit: 100,
    status: status || undefined,
    client: client || undefined,
  })

  const rows = useMemo(() => runs.data ?? [], [runs.data])

  if (runs.isLoading) return <Spinner label="Loading run history…" />
  if (runs.error) {
    return (
      <ErrorState
        title="Unable to load history"
        message={runs.error instanceof Error ? runs.error.message : undefined}
        onRetry={() => void runs.refetch()}
      />
    )
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        <Button variant={!status ? 'primary' : 'secondary'} onClick={() => setStatus('')}>
          All statuses
        </Button>
        {(['SUCCESS', 'FAILED', 'CANCELLED', 'RUNNING', 'QUEUED'] as const).map((s) => (
          <Button
            key={s}
            variant={status === s ? 'primary' : 'ghost'}
            onClick={() => setStatus(s)}
          >
            {s}
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant={!client ? 'secondary' : 'ghost'} onClick={() => setClient('')}>
          All clients
        </Button>
        {(clients.data ?? []).map((c) => (
          <Button
            key={c.code}
            variant={client === c.code ? 'primary' : 'ghost'}
            onClick={() => setClient(c.code)}
          >
            {c.code}
          </Button>
        ))}
      </div>

      <Panel>
        <PanelHeader title="Run History" description="From runtime/runs/*/run.json" />
        {rows.length === 0 ? (
          <EmptyState title="No runs yet" description="Execute a pipeline from the wizard." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">
                <tr>
                  <th className="px-5 py-3">Run ID</th>
                  <th className="px-5 py-3">Date</th>
                  <th className="px-5 py-3">Client</th>
                  <th className="px-5 py-3">Geographies</th>
                  <th className="px-5 py-3">Reports</th>
                  <th className="px-5 py-3">Duration</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {rows.map((r) => (
                  <tr key={r.run_id} className="hover:bg-[var(--accent-soft)]/40">
                    <td className="px-5 py-3 font-mono text-xs">{r.run_id}</td>
                    <td className="px-5 py-3 text-xs text-[var(--fg-muted)]">
                      {r.started_at ?? '—'}
                    </td>
                    <td className="px-5 py-3 font-mono text-xs">{r.client.join(', ')}</td>
                    <td className="px-5 py-3 font-mono text-xs">{r.geographies.join(', ')}</td>
                    <td className="max-w-[180px] truncate px-5 py-3 text-xs">
                      {r.reports.join(', ')}
                    </td>
                    <td className="px-5 py-3 font-mono text-xs">
                      {formatDuration(r.duration_seconds)}
                    </td>
                    <td className="px-5 py-3">
                      <Badge tone={tone(r.status)}>{r.status}</Badge>
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-1">
                        <Link to={`/pipeline/runs/${r.run_id}`}>
                          <Button variant="ghost" className="!px-2 !py-1 text-xs">
                            View
                          </Button>
                        </Link>
                        <Link to={`/pipeline/runs/${r.run_id}`}>
                          <Button variant="ghost" className="!px-2 !py-1 text-xs">
                            Logs
                          </Button>
                        </Link>
                        <Link
                          to="/pipeline/run"
                          state={{
                            clients: r.client,
                            geos: r.geographies,
                            reports: r.reports,
                          }}
                        >
                          <Button variant="ghost" className="!px-2 !py-1 text-xs">
                            Rerun
                          </Button>
                        </Link>
                      </div>
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
