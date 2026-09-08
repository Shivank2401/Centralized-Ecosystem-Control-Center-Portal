import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import type { ReportStage } from '@/types'

type StageRow = ReportStage & { report_count?: number; package_exists?: boolean; enabled?: boolean }

export function ConfigStagesPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const stages = useQuery({ queryKey: ['config-stages'], queryFn: api.configStages })
  const [edit, setEdit] = useState<(StageRow & { isNew?: boolean }) | null>(null)

  const save = useMutation({
    mutationFn: () => {
      if (!edit) throw new Error('none')
      return api.configSaveStage(
        edit.key,
        {
          label: edit.label,
          order: edit.order ?? 50,
          clients: edit.clients,
          enabled: edit.enabled ?? true,
          package_path: edit.package_path,
        },
        Boolean(edit.isNew),
      )
    },
    onSuccess: () => {
      toast.push({ kind: 'success', title: 'Stage saved' })
      setEdit(null)
      void qc.invalidateQueries({ queryKey: ['config-stages'] })
    },
    onError: (e) =>
      toast.push({ kind: 'error', title: 'Save failed', description: e instanceof Error ? e.message : undefined }),
  })

  if (stages.isLoading) return <Spinner />
  if (stages.error) return <ErrorState title="Unable to load stages" onRetry={() => void stages.refetch()} />

  const rows = (stages.data ?? []) as StageRow[]

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Stages"
          description="report.yaml → report_stages · package under report_script/"
          action={
            <Button
              onClick={() =>
                setEdit({
                  key: 'new_stage',
                  label: 'Stage: new_stage',
                  order: 50,
                  enabled: true,
                  package_path: 'report_script/new_stage',
                  isNew: true,
                })
              }
            >
              Create stage
            </Button>
          }
        />
        {rows.length === 0 ? (
          <EmptyState title="No stages" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] uppercase text-[var(--fg-muted)]">
                <tr>
                  <th className="px-5 py-2">Stage</th>
                  <th className="px-5 py-2">Package</th>
                  <th className="px-5 py-2">Reports</th>
                  <th className="px-5 py-2">Status</th>
                  <th className="px-5 py-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {rows.map((s) => (
                  <tr key={s.key}>
                    <td className="px-5 py-2">
                      <p className="font-medium">{s.label}</p>
                      <p className="font-mono text-xs text-[var(--fg-muted)]">{s.key}</p>
                    </td>
                    <td className="px-5 py-2 font-mono text-[11px] text-[var(--fg-muted)]">{s.package_path}</td>
                    <td className="px-5 py-2 font-mono text-xs">{s.report_count ?? '—'}</td>
                    <td className="px-5 py-2">
                      <Badge tone={s.package_exists === false ? 'danger' : 'ok'}>
                        {s.package_exists === false ? 'missing pkg' : 'ok'}
                      </Badge>
                    </td>
                    <td className="px-5 py-2">
                      <Button variant="secondary" onClick={() => setEdit({ ...s })}>
                        Edit
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {edit ? (
        <Panel>
          <PanelHeader title={edit.isNew ? 'Create stage' : `Edit ${edit.key}`} />
          <div className="grid gap-3 p-5 sm:grid-cols-2">
            {edit.isNew ? (
              <label className="space-y-1 text-sm">
                <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Key</span>
                <input
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                  value={edit.key}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'),
                      package_path: `report_script/${e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_')}`,
                    })
                  }
                />
              </label>
            ) : null}
            <label className="space-y-1 text-sm">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Label</span>
              <input
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                value={edit.label}
                onChange={(e) => setEdit({ ...edit, label: e.target.value })}
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Order</span>
              <input
                type="number"
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                value={edit.order ?? 50}
                onChange={(e) => setEdit({ ...edit, order: Number(e.target.value) })}
              />
            </label>
            <label className="space-y-1 text-sm sm:col-span-2">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Package path</span>
              <input
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-xs"
                value={edit.package_path ?? ''}
                onChange={(e) => setEdit({ ...edit, package_path: e.target.value })}
              />
            </label>
          </div>
          <div className="flex gap-2 border-t border-[var(--border)] px-5 py-3">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              Save
            </Button>
            <Button variant="ghost" onClick={() => setEdit(null)}>
              Cancel
            </Button>
          </div>
        </Panel>
      ) : null}
    </div>
  )
}
