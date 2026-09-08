import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, CircleX, Lock } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'

type EnvVar = {
  key: string
  set: boolean
  required: boolean
  secret: boolean
  path_like: boolean
  path_exists: boolean | null
  category: string
  category_ui?: string
}

export function ConfigEnvironmentPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const env = useQuery({ queryKey: ['config-environment'], queryFn: api.configEnvironment })
  const [editKey, setEditKey] = useState<string | null>(null)
  const [pathValue, setPathValue] = useState('')

  const save = useMutation({
    mutationFn: () => api.configSetEnvPath(editKey!, pathValue),
    onSuccess: (data) => {
      toast.push({
        kind: data.accessible ? 'success' : 'info',
        title: `${data.key} updated`,
        description: data.accessible ? 'Path accessible' : 'Saved but path not found on disk',
      })
      setEditKey(null)
      setPathValue('')
      void qc.invalidateQueries({ queryKey: ['config-environment'] })
      void qc.invalidateQueries({ queryKey: ['environment'] })
    },
    onError: (e) =>
      toast.push({ kind: 'error', title: 'Update failed', description: e instanceof Error ? e.message : undefined }),
  })

  if (env.isLoading) return <Spinner label="Checking environment…" />
  if (env.error) {
    return (
      <ErrorState
        title="Unable to load environment"
        message={env.error instanceof Error ? env.error.message : undefined}
        onRetry={() => void env.refetch()}
      />
    )
  }

  const data = env.data as typeof env.data & {
    dotenv_found?: boolean
    python_ok?: boolean
    repo_ok?: boolean
    variables: EnvVar[]
  }

  const vars = data.variables ?? []

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Paths & Environment"
          description="Local .env is the source of truth — secret values never leave this machine via the API"
        />
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-4">
          <Badge tone={data.ok ? 'ok' : 'danger'}>
            {data.ok ? 'required keys set' : `${data.required_missing?.length ?? 0} required missing`}
          </Badge>
          <Badge tone={data.dotenv_found ? 'ok' : 'warn'}>.env {data.dotenv_found ? 'found' : 'missing'}</Badge>
          <Badge tone="ok">Python available</Badge>
          <Badge tone="ok">Repository available</Badge>
        </div>
        <p className="px-5 py-3 text-xs text-[var(--fg-muted)]">{data.note}</p>
      </Panel>

      <VarTable
        title="Path / file variables"
        rows={vars.filter((v) => !v.secret && v.path_like)}
        onChangePath={(key) => {
          setEditKey(key)
          setPathValue('')
        }}
      />
      <VarTable title="Secrets (status only)" rows={vars.filter((v) => v.secret)} />
      <VarTable title="Other configuration" rows={vars.filter((v) => !v.secret && !v.path_like)} />

      {editKey ? (
        <Panel>
          <PanelHeader title={`Change path · ${editKey}`} />
          <div className="space-y-3 p-5">
            <p className="text-xs text-[var(--fg-muted)]">
              Enter an absolute path for this machine. Value is written to local .env only.
            </p>
            <input
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm"
              placeholder="C:\path\to\folder-or-file"
              value={pathValue}
              onChange={(e) => setPathValue(e.target.value)}
            />
            <div className="flex gap-2">
              <Button onClick={() => save.mutate()} disabled={!pathValue.trim() || save.isPending}>
                Save to .env
              </Button>
              <Button variant="ghost" onClick={() => setEditKey(null)}>
                Cancel
              </Button>
            </div>
          </div>
        </Panel>
      ) : null}
    </div>
  )
}

function VarTable({
  title,
  rows,
  onChangePath,
}: {
  title: string
  rows: EnvVar[]
  onChangePath?: (key: string) => void
}) {
  return (
    <Panel>
      <PanelHeader title={title} description={`${rows.length} variables`} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-[var(--border)] text-[11px] uppercase text-[var(--fg-muted)]">
            <tr>
              <th className="px-5 py-3">Key</th>
              <th className="px-5 py-3">Status</th>
              <th className="px-5 py-3">Path</th>
              <th className="px-5 py-3">Actions</th>
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
                      <CheckCircle2 className="h-4 w-4" /> configured
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
                        ? 'accessible'
                        : row.path_exists === false
                          ? 'not accessible'
                          : 'hidden'}
                </td>
                <td className="px-5 py-3">
                  {onChangePath && row.path_like && !row.secret ? (
                    <Button variant="secondary" onClick={() => onChangePath(row.key)}>
                      Change path
                    </Button>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
