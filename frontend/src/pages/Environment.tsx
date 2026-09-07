import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, CircleX, Lock } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { api } from '@/services/api'

export function EnvironmentPage() {
  const env = useQuery({ queryKey: ['environment'], queryFn: api.environment })

  if (env.isLoading) return <Spinner label="Checking environment…" />
  if (env.error) {
    return (
      <ErrorState
        title="Unable to load environment status"
        message={env.error instanceof Error ? env.error.message : undefined}
        onRetry={() => void env.refetch()}
      />
    )
  }

  const data = env.data!
  const required = data.variables.filter((v) => v.required)
  const optional = data.variables.filter((v) => !v.required)

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Environment Manager"
          description="Machine-local .env status — values never leave the API host"
        />
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-4">
          <Badge tone={data.ok ? 'ok' : 'danger'}>
            {data.ok ? 'required keys set' : `${data.required_missing.length} required missing`}
          </Badge>
          {data.path_missing.length ? (
            <Badge tone="warn">{data.path_missing.length} path(s) missing on disk</Badge>
          ) : null}
        </div>
        <p className="px-5 py-3 text-xs text-[var(--fg-muted)]">{data.note}</p>
      </Panel>

      <VarTable title="Required (from clients)" rows={required} />
      <VarTable title="Optional / integrations" rows={optional} />
    </div>
  )
}

function VarTable({
  title,
  rows,
}: {
  title: string
  rows: {
    key: string
    set: boolean
    required: boolean
    secret: boolean
    path_like: boolean
    path_exists: boolean | null
    category: string
  }[]
}) {
  return (
    <Panel>
      <PanelHeader title={title} description={`${rows.length} variables`} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-[var(--border)] text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">
            <tr>
              <th className="px-5 py-3 font-medium">Key</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Path</th>
              <th className="px-5 py-3 font-medium">Category</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {rows.map((row) => (
              <tr key={row.key}>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2 font-mono text-xs">
                    {row.secret ? <Lock className="h-3.5 w-3.5 text-[var(--fg-muted)]" /> : null}
                    {row.key}
                  </div>
                </td>
                <td className="px-5 py-3">
                  {row.set ? (
                    <span className="inline-flex items-center gap-1 text-[var(--color-ok)]">
                      <CheckCircle2 className="h-4 w-4" /> set
                    </span>
                  ) : row.required ? (
                    <span className="inline-flex items-center gap-1 text-[var(--color-danger)]">
                      <CircleX className="h-4 w-4" /> missing
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[var(--fg-muted)]">
                      <CircleAlert className="h-4 w-4" /> unset
                    </span>
                  )}
                </td>
                <td className="px-5 py-3 font-mono text-xs text-[var(--fg-muted)]">
                  {!row.path_like
                    ? '—'
                    : !row.set
                      ? '—'
                      : row.path_exists === true
                        ? 'exists'
                        : row.path_exists === false
                          ? 'not found'
                          : 'hidden'}
                </td>
                <td className="px-5 py-3 font-mono text-xs text-[var(--fg-muted)]">{row.category}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
