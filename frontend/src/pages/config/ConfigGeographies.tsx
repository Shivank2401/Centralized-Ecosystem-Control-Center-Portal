import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import type { Geography } from '@/types'

export function ConfigGeographiesPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const clients = useQuery({ queryKey: ['config-clients'], queryFn: api.configClients })
  const [client, setClient] = useState('')
  const [q, setQ] = useState('')
  const [edit, setEdit] = useState<(Geography & { isNew?: boolean }) | null>(null)

  const geos = useQuery({
    queryKey: ['config-geographies', client || 'all'],
    queryFn: () => api.configGeographies(client || undefined),
  })

  const save = useMutation({
    mutationFn: () => {
      if (!edit) throw new Error('none')
      return api.configSaveGeography(
        edit.client,
        edit.country_code,
        {
          country_code: edit.country_code,
          cogs_sheet_name: edit.cogs_sheet_name,
          country_currency: edit.country_currency,
          orders_sales_channel: edit.orders_sales_channel,
          enabled: edit.enabled,
        },
        Boolean(edit.isNew),
      )
    },
    onSuccess: () => {
      toast.push({ kind: 'success', title: 'Geography saved' })
      setEdit(null)
      void qc.invalidateQueries({ queryKey: ['config-geographies'] })
      void qc.invalidateQueries({ queryKey: ['config-clients'] })
    },
    onError: (e) =>
      toast.push({ kind: 'error', title: 'Save failed', description: e instanceof Error ? e.message : undefined }),
  })

  const filtered = useMemo(() => {
    return (geos.data ?? []).filter((g) => {
      if (!q) return true
      const s = q.toLowerCase()
      return (
        g.country_code.toLowerCase().includes(s) ||
        g.client.toLowerCase().includes(s) ||
        g.cogs_sheet_name.toLowerCase().includes(s)
      )
    })
  }, [geos.data, q])

  if (geos.isLoading || clients.isLoading) return <Spinner />
  if (geos.error) return <ErrorState title="Unable to load geographies" onRetry={() => void geos.refetch()} />

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Geographies"
          description="Edits config_manager/geography.yaml"
          action={
            <Button
              onClick={() => {
                const c = client || clients.data?.[0]?.code || 'ESH'
                setEdit({
                  client: c,
                  country_code: 'XX',
                  cogs_sheet_name: '',
                  country_currency: '',
                  orders_sales_channel: '',
                  enabled: true,
                  isNew: true,
                })
              }}
            >
              Add geography
            </Button>
          }
        />
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-3">
          <Button variant={!client ? 'primary' : 'ghost'} onClick={() => setClient('')}>
            All
          </Button>
          {(clients.data ?? []).map((c) => (
            <Button key={c.code} variant={client === c.code ? 'primary' : 'ghost'} onClick={() => setClient(c.code)}>
              {c.code}
            </Button>
          ))}
          <input
            className="rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm"
            placeholder="Search…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {filtered.length === 0 ? (
          <EmptyState title="No geographies" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[700px] text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] uppercase text-[var(--fg-muted)]">
                <tr>
                  <th className="px-5 py-2">Code</th>
                  <th className="px-5 py-2">Client</th>
                  <th className="px-5 py-2">COGS sheet</th>
                  <th className="px-5 py-2">Currency</th>
                  <th className="px-5 py-2">Status</th>
                  <th className="px-5 py-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filtered.map((g) => (
                  <tr key={`${g.client}-${g.country_code}`}>
                    <td className="px-5 py-2 font-mono font-semibold">{g.country_code}</td>
                    <td className="px-5 py-2 font-mono text-xs">{g.client}</td>
                    <td className="px-5 py-2 font-mono text-xs">{g.cogs_sheet_name}</td>
                    <td className="px-5 py-2 font-mono text-xs">{g.country_currency}</td>
                    <td className="px-5 py-2">
                      <Badge tone={g.enabled ? 'ok' : 'warn'}>{g.enabled ? 'enabled' : 'disabled'}</Badge>
                    </td>
                    <td className="px-5 py-2">
                      <Button variant="secondary" onClick={() => setEdit({ ...g })}>
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
          <PanelHeader title={`${edit.isNew ? 'Add' : 'Edit'} ${edit.client}/${edit.country_code}`} />
          <div className="grid gap-3 p-5 sm:grid-cols-2">
            {edit.isNew ? (
              <>
                <label className="space-y-1 text-sm">
                  <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Client</span>
                  <select
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                    value={edit.client}
                    onChange={(e) => setEdit({ ...edit, client: e.target.value })}
                  >
                    {(clients.data ?? []).map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.code}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1 text-sm">
                  <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Code</span>
                  <input
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                    value={edit.country_code}
                    onChange={(e) => setEdit({ ...edit, country_code: e.target.value.toUpperCase() })}
                  />
                </label>
              </>
            ) : null}
            <label className="space-y-1 text-sm">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">COGS sheet</span>
              <input
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                value={edit.cogs_sheet_name}
                onChange={(e) => setEdit({ ...edit, cogs_sheet_name: e.target.value })}
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Currency</span>
              <input
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                value={edit.country_currency}
                onChange={(e) => setEdit({ ...edit, country_currency: e.target.value })}
              />
            </label>
            <label className="space-y-1 text-sm sm:col-span-2">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Sales channel</span>
              <input
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                value={edit.orders_sales_channel}
                onChange={(e) => setEdit({ ...edit, orders_sales_channel: e.target.value })}
              />
            </label>
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
            <Button variant="ghost" onClick={() => setEdit(null)}>
              Cancel
            </Button>
          </div>
        </Panel>
      ) : null}
    </div>
  )
}
