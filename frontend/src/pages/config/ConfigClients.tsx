import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import type { Client } from '@/types'

const empty: Client = {
  code: '',
  name: '',
  client_id: '',
  enabled: true,
  data_root_env: '',
  cogs_path_env: '',
  geographies: [],
  layout: '',
  package: '',
}

export function ConfigClientsPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<'all' | 'enabled' | 'disabled'>('all')
  const [edit, setEdit] = useState<Client | null>(null)
  const [creating, setCreating] = useState(false)

  const list = useQuery({ queryKey: ['config-clients'], queryFn: api.configClients })
  const save = useMutation({
    mutationFn: () => {
      if (!edit) throw new Error('No client')
      const code = edit.code.toUpperCase()
      const body = {
        name: edit.name,
        client_id: edit.client_id,
        enabled: edit.enabled,
        data_root_env: edit.data_root_env,
        cogs_path_env: edit.cogs_path_env,
        package: edit.package || '',
        layout: edit.layout || '',
        geographies: edit.geographies,
      }
      return api.configSaveClient(code, body, creating)
    },
    onSuccess: () => {
      toast.push({ kind: 'success', title: 'Client saved' })
      setEdit(null)
      setCreating(false)
      void qc.invalidateQueries({ queryKey: ['config-clients'] })
      void qc.invalidateQueries({ queryKey: ['config-overview'] })
      void qc.invalidateQueries({ queryKey: ['clients'] })
    },
    onError: (e) =>
      toast.push({ kind: 'error', title: 'Save failed', description: e instanceof Error ? e.message : undefined }),
  })

  const toggle = useMutation({
    mutationFn: ({ code, enabled }: { code: string; enabled: boolean }) =>
      api.configEnableClient(code, enabled),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['config-clients'] })
      toast.push({ kind: 'success', title: 'Client updated' })
    },
  })

  const filtered = useMemo(() => {
    return (list.data ?? []).filter((c) => {
      if (status === 'enabled' && !c.enabled) return false
      if (status === 'disabled' && c.enabled) return false
      if (!q) return true
      const s = q.toLowerCase()
      return c.code.toLowerCase().includes(s) || c.name.toLowerCase().includes(s)
    })
  }, [list.data, q, status])

  if (list.isLoading) return <Spinner />
  if (list.error) {
    return (
      <ErrorState
        title="Unable to load clients"
        onRetry={() => void list.refetch()}
      />
    )
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Clients"
          description="Edits config_manager/client.yaml — paths stay as env var names"
          action={
            <Button
              onClick={() => {
                setCreating(true)
                setEdit({ ...empty, code: 'NEW', data_root_env: 'NEW_DATA_ROOT', cogs_path_env: 'NEW_COGS_PATH' })
              }}
            >
              Add client
            </Button>
          }
        />
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-3">
          <input
            className="rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm"
            placeholder="Search…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          {(['all', 'enabled', 'disabled'] as const).map((s) => (
            <Button key={s} variant={status === s ? 'primary' : 'ghost'} onClick={() => setStatus(s)}>
              {s}
            </Button>
          ))}
        </div>
        {filtered.length === 0 ? (
          <EmptyState title="No clients match" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] uppercase text-[var(--fg-muted)]">
                <tr>
                  <th className="px-5 py-2">Client</th>
                  <th className="px-5 py-2">Name</th>
                  <th className="px-5 py-2">Status</th>
                  <th className="px-5 py-2">Geographies</th>
                  <th className="px-5 py-2">Reports</th>
                  <th className="px-5 py-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filtered.map((c) => (
                  <tr key={c.code}>
                    <td className="px-5 py-2 font-mono font-semibold">{c.code}</td>
                    <td className="px-5 py-2">{c.name}</td>
                    <td className="px-5 py-2">
                      <Badge tone={c.enabled ? 'ok' : 'warn'}>{c.enabled ? 'enabled' : 'disabled'}</Badge>
                    </td>
                    <td className="px-5 py-2 font-mono text-xs">{c.geographies.length}</td>
                    <td className="px-5 py-2 font-mono text-xs">
                      {(c as Client & { report_count?: number }).report_count ?? '—'}
                    </td>
                    <td className="px-5 py-2">
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setCreating(false)
                            setEdit({ ...c })
                          }}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => toggle.mutate({ code: c.code, enabled: !c.enabled })}
                        >
                          {c.enabled ? 'Disable' : 'Enable'}
                        </Button>
                      </div>
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
          <PanelHeader title={creating ? 'Add client' : `Edit ${edit.code}`} />
          <div className="grid gap-3 p-5 sm:grid-cols-2">
            {creating ? (
              <Field label="Code">
                <input
                  className="field"
                  value={edit.code}
                  onChange={(e) => setEdit({ ...edit, code: e.target.value.toUpperCase() })}
                />
              </Field>
            ) : null}
            <Field label="Name">
              <input className="field" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
            </Field>
            <Field label="Client ID">
              <input
                className="field"
                value={edit.client_id}
                onChange={(e) => setEdit({ ...edit, client_id: e.target.value })}
              />
            </Field>
            <Field label="data_root_env">
              <input
                className="field font-mono"
                value={edit.data_root_env}
                onChange={(e) => setEdit({ ...edit, data_root_env: e.target.value })}
              />
            </Field>
            <Field label="cogs_path_env">
              <input
                className="field font-mono"
                value={edit.cogs_path_env}
                onChange={(e) => setEdit({ ...edit, cogs_path_env: e.target.value })}
              />
            </Field>
            <Field label="layout">
              <input
                className="field"
                value={edit.layout || ''}
                onChange={(e) => setEdit({ ...edit, layout: e.target.value })}
              />
            </Field>
            <Field label="package">
              <input
                className="field"
                value={edit.package || ''}
                onChange={(e) => setEdit({ ...edit, package: e.target.value })}
              />
            </Field>
            <Field label="Geographies (comma)">
              <input
                className="field font-mono"
                value={edit.geographies.join(',')}
                onChange={(e) =>
                  setEdit({
                    ...edit,
                    geographies: e.target.value
                      .split(',')
                      .map((x) => x.trim().toUpperCase())
                      .filter(Boolean),
                  })
                }
              />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={edit.enabled}
                onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })}
              />
              Enabled
            </label>
          </div>
          <div className="flex gap-2 border-t border-[var(--border)] px-5 py-3">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              Save
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setEdit(null)
                setCreating(false)
              }}
            >
              Cancel
            </Button>
          </div>
          <style>{`.field{width:100%;border:1px solid var(--border);border-radius:.375rem;background:var(--bg);padding:.5rem .75rem;font-size:.875rem}`}</style>
        </Panel>
      ) : null}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">{label}</span>
      {children}
    </label>
  )
}
