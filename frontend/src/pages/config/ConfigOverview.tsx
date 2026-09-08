import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, CircleX } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'

type Overview = {
  version: string
  counts: Record<string, number>
  last_modified?: string
  pipeline_busy?: string | null
  health: {
    ok: boolean
    errors: { name: string; message: string; level: string }[]
    warnings: { name: string; message: string; level: string }[]
    checks: { name: string; ok: boolean; level: string; message: string }[]
  }
}

export function ConfigOverviewPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['config-overview'], queryFn: () => api.configOverview() as Promise<Overview> })
  const validate = useMutation({
    mutationFn: api.configValidate,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['config-overview'] })
      toast.push({ kind: 'success', title: 'Validation complete' })
    },
  })

  if (q.isLoading) return <Spinner label="Loading configuration overview…" />
  if (q.error) {
    return (
      <ErrorState
        title="Unable to load configuration overview"
        message={q.error instanceof Error ? q.error.message : undefined}
        onRetry={() => void q.refetch()}
      />
    )
  }

  const data = q.data!
  const c = data.counts

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Configuration Overview"
          description={`config_manager is the source of truth · version ${data.version}`}
          action={
            <Button onClick={() => validate.mutate()} disabled={validate.isPending}>
              Validate Configuration
            </Button>
          }
        />
        {data.pipeline_busy ? (
          <p className="border-b border-[var(--border)] px-5 py-2 text-sm text-[var(--color-warn)]">
            Pipeline {data.pipeline_busy} is active — avoid changing report.yaml until it finishes.
          </p>
        ) : null}
        <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ['Clients', `${c.clients_active}/${c.clients_total} active`],
            ['Geographies', `${c.geographies_active}/${c.geographies_total} active`],
            ['Stages', String(c.stages_total)],
            ['Reports', `${c.reports_enabled} on · ${c.reports_disabled} off`],
            ['Sequences', String(c.sequences)],
            ['Last modified', data.last_modified?.slice(0, 19) ?? '—'],
          ].map(([label, value]) => (
            <div key={label} className="rounded-md border border-[var(--border)] px-3 py-2">
              <p className="font-mono text-[10px] tracking-wider text-[var(--fg-muted)] uppercase">
                {label}
              </p>
              <p className="mt-1 text-sm font-semibold">{value}</p>
            </div>
          ))}
        </div>
      </Panel>

      <Panel>
        <PanelHeader
          title="Configuration Health"
          action={
            <Badge tone={data.health.ok ? 'ok' : 'danger'}>
              {data.health.ok ? 'valid' : 'issues'}
            </Badge>
          }
        />
        <ul className="divide-y divide-[var(--border)]">
          {data.health.checks
            .filter((x) => ['yaml:client.yaml', 'yaml:geography.yaml', 'yaml:report.yaml', 'yaml:run_sequences.yaml', 'clients', 'geographies', 'environment'].includes(x.name) || !x.ok)
            .slice(0, 40)
            .map((x) => (
              <li key={x.name} className="flex items-start gap-3 px-5 py-2 text-sm">
                {x.ok ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 text-[var(--color-ok)]" />
                ) : x.level === 'WARNING' ? (
                  <CircleAlert className="mt-0.5 h-4 w-4 text-[var(--color-warn)]" />
                ) : (
                  <CircleX className="mt-0.5 h-4 w-4 text-[var(--color-danger)]" />
                )}
                <div>
                  <p className="font-mono text-xs font-semibold">{x.name}</p>
                  <p className="text-[var(--fg-muted)]">{x.message}</p>
                </div>
              </li>
            ))}
        </ul>
      </Panel>
    </div>
  )
}
