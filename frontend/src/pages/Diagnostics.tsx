import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { Activity, CheckCircle2, CircleAlert, CircleX, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { api } from '@/services/api'

export function DiagnosticsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const diag = useQuery({ queryKey: ['diagnostics'], queryFn: api.diagnostics, refetchInterval: 15_000 })
  const refresh = useMutation({
    mutationFn: api.refreshConfig,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['diagnostics'] })
      void qc.invalidateQueries({ queryKey: ['clients'] })
      void qc.invalidateQueries({ queryKey: ['reports'] })
    },
  })

  if (diag.isLoading) return <Spinner label="Running diagnostics…" />
  if (diag.error) {
    return (
      <ErrorState
        title="Diagnostics unavailable"
        message={diag.error instanceof Error ? diag.error.message : undefined}
        onRetry={() => void diag.refetch()}
      />
    )
  }

  const data = diag.data!

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="System Diagnostics"
          description="Frontend → API → pipeline_engine → config / modules"
          action={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => void diag.refetch()}>
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
              <Button variant="ghost" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
                Reload YAML
              </Button>
            </div>
          }
        />
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--border)] px-5 py-4">
          <Badge tone={data.ok ? 'ok' : 'danger'}>{data.ok ? 'healthy' : 'issues'}</Badge>
          <span className="font-mono text-xs text-[var(--fg-muted)]">
            phase {data.phase} · Python {data.python}
          </span>
          {data.active_run_id ? (
            <Button variant="secondary" onClick={() => navigate(`/pipeline/runs/${data.active_run_id}`)}>
              <Activity className="h-4 w-4" />
              Active: {data.active_run_id}
            </Button>
          ) : null}
        </div>
        <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(data.counts).map(([k, v]) => (
            <div key={k} className="rounded-md border border-[var(--border)] px-3 py-2">
              <p className="font-mono text-[10px] tracking-wider text-[var(--fg-muted)] uppercase">
                {k.replace(/_/g, ' ')}
              </p>
              <p className="text-2xl font-semibold tabular-nums">{v}</p>
            </div>
          ))}
        </div>
        <ul className="divide-y divide-[var(--border)]">
          {data.checks.map((c) => (
            <li key={c.name} className="flex items-start gap-3 px-5 py-3 text-sm">
              {c.ok ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-ok)]" />
              ) : c.level === 'WARN' ? (
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warn)]" />
              ) : (
                <CircleX className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-danger)]" />
              )}
              <div>
                <p className="font-mono text-xs font-semibold">{c.name}</p>
                <p className="text-[var(--fg-muted)]">{c.message}</p>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
      <p className="text-center text-xs text-[var(--fg-muted)]">
        Also see{' '}
        <Link className="text-[var(--accent)] underline" to="/config/environment">
          Environment
        </Link>{' '}
        and{' '}
        <Link className="text-[var(--accent)] underline" to="/developer/validation">
          Validation
        </Link>
        .
      </p>
    </div>
  )
}
