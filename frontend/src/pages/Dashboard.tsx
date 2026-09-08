import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2, CircleDashed, Play } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import {
  useActiveRun,
  useClients,
  useHealth,
  useReports,
  useRuns,
  useSequences,
} from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { api } from '@/services/api'
import { formatDuration } from '@/pages/RunDetail'

export function DashboardPage() {
  const clients = useClients()
  const reports = useReports({ enabledOnly: false })
  const sequences = useSequences()
  const health = useHealth()
  const active = useActiveRun()
  const recent = useRuns({ limit: 5 })
  const diag = useQuery({ queryKey: ['diagnostics'], queryFn: api.diagnostics, staleTime: 30_000 })

  if (clients.isLoading || reports.isLoading) return <Spinner label="Loading ecosystem status…" />
  if (clients.error || reports.error) {
    const err = clients.error || reports.error
    return (
      <ErrorState
        title="Unable to load dashboard"
        message={err instanceof Error ? err.message : 'API request failed'}
        onRetry={() => {
          void clients.refetch()
          void reports.refetch()
        }}
      />
    )
  }

  const clientList = clients.data ?? []
  const reportList = reports.data ?? []
  const enabled = reportList.filter((r) => r.enabled).length
  const disabled = reportList.length - enabled
  const geos = [...new Set(clientList.flatMap((c) => c.geographies))]

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <section className="relative overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] px-7 py-8">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(15,118,110,0.14),transparent_55%)] dark:bg-[radial-gradient(ellipse_at_top_right,rgba(45,212,191,0.12),transparent_55%)]" />
        <div className="relative">
          <p className="font-mono text-xs tracking-[0.22em] text-[var(--accent)] uppercase">
            Inventory Ecosystem
          </p>
          <h2 className="mt-2 max-w-xl text-3xl font-semibold tracking-tight">
            Data engineering & Scripts Control Center
          </h2>
          <p className="mt-2 max-w-xl text-sm text-[var(--fg-muted)]">
            Orchestrate clients, geographies, and report stages without leaving the portal. ETL
            stays in Python — this layer runs the control plane.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Link to="/pipeline/run">
              <Button>
                <Play className="h-4 w-4" />
                Run Pipeline
              </Button>
            </Link>
            <Link to="/developer/diagnostics">
              <Button variant="secondary">Diagnostics</Button>
            </Link>
          </div>
        </div>
      </section>

      {active.data ? (
        <Panel>
          <PanelHeader
            title="Active run"
            description={active.data.run_id}
            action={
              <Link to={`/pipeline/runs/${active.data.run_id}`}>
                <Button variant="secondary">
                  Open <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            }
          />
          <div className="flex flex-wrap items-center gap-3 px-5 py-4 text-sm">
            <Badge tone="accent">{active.data.status}</Badge>
            <span className="font-mono text-xs text-[var(--fg-muted)]">
              {Math.round(active.data.progress * 100)}% · {active.data.current_report ?? 'queued'}
            </span>
          </div>
        </Panel>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: 'Clients', value: clientList.length },
          { label: 'Reports', value: reportList.length },
          { label: 'Enabled', value: enabled },
          { label: 'Geographies', value: geos.length },
        ].map((stat) => (
          <div
            key={stat.label}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] px-5 py-4"
          >
            <p className="font-mono text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">
              {stat.label}
            </p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">{stat.value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel>
          <PanelHeader title="Clients" description="Enabled client codes from client.yaml" />
          <div className="flex flex-wrap gap-2 p-5">
            {clientList.map((c) => (
              <div
                key={c.code}
                className="min-w-[7rem] rounded-md border border-[var(--border)] px-3 py-2"
              >
                <p className="font-mono text-sm font-semibold">{c.code}</p>
                <p className="text-xs text-[var(--fg-muted)]">{c.name}</p>
                <p className="mt-1 font-mono text-[10px] text-[var(--fg-muted)]">
                  {c.geographies.join(' · ')}
                </p>
              </div>
            ))}
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title="System Health"
            description="API + diagnostics"
            action={
              <Link to="/developer/diagnostics">
                <Button variant="ghost">Details</Button>
              </Link>
            }
          />
          <ul className="space-y-3 p-5 text-sm">
            {[
              {
                label: 'Python API',
                ok: health.isSuccess,
                detail: health.isSuccess
                  ? `Reachable · phase ${health.data?.phase ?? '?'}`
                  : 'Offline — start portal.py',
              },
              {
                label: 'Configuration',
                ok: clientList.length > 0 && reportList.length > 0,
                detail: `${clientList.length} clients · ${reportList.length} reports`,
              },
              {
                label: 'Diagnostics',
                ok: diag.data?.ok ?? false,
                detail: diag.isLoading
                  ? 'Checking…'
                  : diag.data
                    ? `${diag.data.counts.missing_modules} missing modules`
                    : 'Unavailable',
              },
              {
                label: 'Disabled reports',
                ok: true,
                detail: `${disabled} disabled`,
              },
            ].map((row) => (
              <li key={row.label} className="flex items-start gap-3">
                {row.ok ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 text-[var(--color-ok)]" />
                ) : (
                  <CircleDashed className="mt-0.5 h-4 w-4 text-[var(--color-warn)]" />
                )}
                <div>
                  <p className="font-medium">{row.label}</p>
                  <p className="text-xs text-[var(--fg-muted)]">{row.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel>
        <PanelHeader
          title="Recent runs"
          description="From runtime/runs"
          action={
            <Link to="/pipeline/history">
              <Button variant="ghost">
                History <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          }
        />
        {(recent.data?.length ?? 0) === 0 ? (
          <EmptyState title="No runs yet" description="Start one from Run Pipeline." />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {(recent.data ?? []).map((run) => (
              <Link
                key={run.run_id}
                to={`/pipeline/runs/${run.run_id}`}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 hover:bg-[var(--accent-soft)]/30"
              >
                <div>
                  <p className="font-mono text-sm">{run.run_id}</p>
                  <p className="text-xs text-[var(--fg-muted)]">
                    {run.client.join(', ')} · {run.reports.length} report(s)
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-[var(--fg-muted)]">
                    {formatDuration(run.duration_seconds)}
                  </span>
                  <Badge
                    tone={
                      run.status === 'SUCCESS'
                        ? 'ok'
                        : run.status === 'FAILED'
                          ? 'danger'
                          : run.status === 'CANCELLED'
                            ? 'warn'
                            : 'accent'
                    }
                  >
                    {run.status}
                  </Badge>
                </div>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      <Panel>
        <PanelHeader
          title="Run Sequences"
          description="From run_sequences.yaml"
          action={
            <Link to="/pipeline/sequences">
              <Button variant="ghost">
                View all <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          }
        />
        {sequences.isLoading ? (
          <Spinner />
        ) : (sequences.data?.length ?? 0) === 0 ? (
          <EmptyState
            title="No run sequences"
            description="Create one from Pipeline → Run Sequences."
          />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {(sequences.data ?? []).map((seq) => (
              <div
                key={seq.id}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
              >
                <div>
                  <p className="font-medium">{seq.label}</p>
                  <p className="font-mono text-xs text-[var(--fg-muted)]">
                    {seq.clients.join(', ')} · {seq.geos.join(', ')} · {seq.reports.length} steps
                  </p>
                </div>
                <Badge tone="accent">{seq.id}</Badge>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}
