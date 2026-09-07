import { Link } from 'react-router-dom'
import { Ban, CheckCircle2, Circle, Loader2 } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRun } from '@/hooks/useApi'
import { useRunLiveLogs } from '@/hooks/useRunLiveLogs'
import { api, ApiError } from '@/services/api'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { cn } from '@/utils/cn'
import type { PipelineRunStatus } from '@/types'

function statusTone(status: PipelineRunStatus): 'ok' | 'warn' | 'danger' | 'accent' | 'neutral' {
  if (status === 'SUCCESS') return 'ok'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED') return 'warn'
  if (status === 'RUNNING') return 'accent'
  return 'neutral'
}

export function RunDetailPage({ runId }: { runId: string }) {
  const run = useRun(runId)
  const live = useRunLiveLogs(runId)
  const toast = useToast()
  const queryClient = useQueryClient()

  const cancel = useMutation({
    mutationFn: () => api.cancelRun(runId),
    onSuccess: () => {
      toast.push({ kind: 'info', title: 'Cancel requested' })
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
    },
    onError: (err) => {
      toast.push({
        kind: 'error',
        title: 'Cancel failed',
        description: err instanceof Error ? err.message : 'Unknown error',
      })
    },
  })

  if (run.isLoading) return <Spinner label="Loading run…" />
  if (run.error) {
    return (
      <ErrorState
        title="Unable to load run"
        message={run.error instanceof Error ? run.error.message : undefined}
        onRetry={() => void run.refetch()}
      />
    )
  }

  const data = run.data
  if (!data) return <EmptyState title="Run not found" />

  const status = live.status ?? data.status
  const progress = live.status ? live.progress : data.progress
  const current = live.currentReport ?? data.current_report
  const completed = live.completed.length ? live.completed : data.completed_reports
  const pending = data.reports.filter((r) => !completed.includes(r) && r !== current)
  const canCancel = status === 'QUEUED' || status === 'RUNNING'

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-xs text-[var(--fg-muted)]">Run #{data.run_id}</p>
          <h2 className="mt-1 text-xl font-semibold">
            {data.client.join(', ')} · {data.geographies.join(', ')}
          </h2>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge tone={statusTone(status)}>{status}</Badge>
            {live.connected ? <Badge tone="accent">live</Badge> : null}
          </div>
        </div>
        <div className="flex gap-2">
          {canCancel ? (
            <Button
              variant="danger"
              disabled={cancel.isPending}
              onClick={() => {
                if (window.confirm('Cancel this pipeline run?')) cancel.mutate()
              }}
            >
              <Ban className="h-4 w-4" />
              Cancel Run
            </Button>
          ) : null}
          <Link to="/pipeline/history">
            <Button variant="secondary">History</Button>
          </Link>
        </div>
      </div>

      <Panel>
        <PanelHeader title="Overall Progress" description={`${Math.round(progress)}%`} />
        <div className="space-y-4 p-5">
          <div className="h-2 overflow-hidden rounded-full bg-[var(--border)]">
            <div
              className="h-full rounded-full bg-[var(--accent)] transition-all"
              style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-3 text-sm">
            <div>
              <p className="font-mono text-[11px] text-[var(--fg-muted)] uppercase">Completed</p>
              <ul className="mt-2 space-y-1">
                {completed.length === 0 ? (
                  <li className="text-[var(--fg-muted)]">—</li>
                ) : (
                  completed.map((r) => (
                    <li key={r} className="flex items-center gap-2">
                      <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-ok)]" />
                      {r}
                    </li>
                  ))
                )}
              </ul>
            </div>
            <div>
              <p className="font-mono text-[11px] text-[var(--fg-muted)] uppercase">Running</p>
              <p className="mt-2 flex items-center gap-2">
                {current ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--accent)]" />
                    {current}
                  </>
                ) : (
                  <span className="text-[var(--fg-muted)]">—</span>
                )}
              </p>
            </div>
            <div>
              <p className="font-mono text-[11px] text-[var(--fg-muted)] uppercase">Pending</p>
              <ul className="mt-2 space-y-1">
                {pending.length === 0 ? (
                  <li className="text-[var(--fg-muted)]">—</li>
                ) : (
                  pending.map((r) => (
                    <li key={r} className="flex items-center gap-2 text-[var(--fg-muted)]">
                      <Circle className="h-3.5 w-3.5" />
                      {r}
                    </li>
                  ))
                )}
              </ul>
            </div>
          </div>
          {data.error ? (
            <p className="rounded-md border border-[var(--color-danger)]/40 bg-red-500/10 px-3 py-2 text-sm text-[var(--color-danger)]">
              {data.error}
            </p>
          ) : null}
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="Live logs" description="runtime/runs/{id}/stdout.log" />
        <pre
          className={cn(
            'max-h-[420px] overflow-auto bg-[#0b0f14] p-4 font-mono text-xs leading-relaxed text-teal-100',
          )}
        >
          {live.text || data.logs.join('\n') || 'Waiting for output…'}
        </pre>
      </Panel>
    </div>
  )
}

export function formatDuration(seconds?: number | null) {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

export function isApiBusyError(err: unknown) {
  return err instanceof ApiError && err.code === 'PIPELINE_BUSY'
}
