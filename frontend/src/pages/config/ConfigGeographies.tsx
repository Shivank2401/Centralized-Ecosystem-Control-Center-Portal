import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import type { Geography, GeographyChannel } from '@/types'

type ChannelDraft = {
  name: string
  excel_sheet: string
  orders_sales_channel: string
  markets: string
  vendors: string
}

type GeoDraft = Geography & {
  isNew?: boolean
  channelDrafts: ChannelDraft[]
}

function channelSearchText(g: Geography): string {
  const entries = Object.entries(g.channels ?? {})
  if (!entries.length) return ''
  return entries
    .flatMap(([n, ch]) => [
      n,
      ch.excel_sheet ?? '',
      ch.orders_sales_channel ?? '',
      ...(ch.markets ?? []),
      ...(ch.vendors ?? []),
      ch.cogs_stem ?? '',
    ])
    .join(' ')
}

function ChannelsCell({ g }: { g: Geography }) {
  const entries = Object.entries(g.channels ?? {})
  if (!entries.length) {
    return <span className="text-[var(--fg-muted)]">—</span>
  }
  return (
    <div className="space-y-2 py-1">
      {entries.map(([name, ch]) => {
        const stem = ch.cogs_stem || `${g.country_code.toLowerCase()}_${name}_cogs`
        const lines: { label: string; value: string }[] = []
        if (ch.excel_sheet) lines.push({ label: 'excel_sheet', value: ch.excel_sheet })
        if (ch.orders_sales_channel) {
          lines.push({ label: 'orders_sales_channel', value: ch.orders_sales_channel })
        }
        if ((ch.markets ?? []).length) {
          lines.push({ label: 'markets', value: (ch.markets ?? []).join(', ') })
        }
        if ((ch.vendors ?? []).length) {
          lines.push({ label: 'vendors', value: (ch.vendors ?? []).join(', ') })
        }
        lines.push({ label: 'local_cogs', value: stem })
        return (
          <div key={name} className="min-w-[220px]">
            <p className="font-mono text-[11px] font-semibold text-[var(--fg)]">{name}</p>
            <ul className="mt-0.5 space-y-0.5 font-mono text-[10px] leading-snug text-[var(--fg-muted)]">
              {lines.map((l) => (
                <li key={l.label}>
                  <span className="text-[var(--fg-muted)]/80">{l.label}:</span> {l.value}
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

function channelsToDrafts(g: Geography): ChannelDraft[] {
  const entries = Object.entries(g.channels ?? {})
  if (!entries.length) {
    return [
      {
        name: g.default_channel || 'amazon',
        excel_sheet: g.cogs_sheet_name || '',
        orders_sales_channel: g.orders_sales_channel || '',
        markets: '',
        vendors: '',
      },
    ]
  }
  return entries.map(([name, ch]) => ({
    name,
    excel_sheet: ch.excel_sheet || '',
    orders_sales_channel: ch.orders_sales_channel || '',
    markets: (ch.markets ?? []).join(', '),
    vendors: (ch.vendors ?? []).join(', '),
  }))
}

function draftsToChannels(drafts: ChannelDraft[]): Record<string, GeographyChannel> {
  const out: Record<string, GeographyChannel> = {}
  for (const d of drafts) {
    const name = d.name.trim().toLowerCase()
    if (!name) continue
    const markets = d.markets
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    const vendors = d.vendors
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    out[name] = {
      excel_sheet: d.excel_sheet.trim(),
      orders_sales_channel: d.orders_sales_channel.trim(),
      markets,
      vendors,
    }
  }
  return out
}

function emptyDraft(client: string): GeoDraft {
  return {
    client,
    country_code: '',
    country_currency: '',
    enabled: true,
    default_channel: 'amazon',
    channels: {},
    isNew: true,
    channelDrafts: [
      {
        name: 'amazon',
        excel_sheet: '',
        orders_sales_channel: '',
        markets: '',
        vendors: '',
      },
    ],
  }
}

export function ConfigGeographiesPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const clients = useQuery({ queryKey: ['config-clients'], queryFn: api.configClients })
  const [client, setClient] = useState('')
  const [q, setQ] = useState('')
  const [edit, setEdit] = useState<GeoDraft | null>(null)

  useEffect(() => {
    if (!client && (clients.data?.length ?? 0) > 0) {
      setClient(clients.data![0].code)
    }
  }, [clients.data, client])

  const geos = useQuery({
    queryKey: ['config-geographies', client],
    queryFn: () => api.configGeographies(client),
    enabled: Boolean(client),
  })

  const save = useMutation({
    mutationFn: () => {
      if (!edit) throw new Error('none')
      const code = edit.country_code.trim().toUpperCase()
      if (!/^[A-Z]{2}$/.test(code)) {
        throw new Error('Geo code must be 2 letters (e.g. UK, IE)')
      }
      if (!edit.country_currency.trim()) {
        throw new Error('Currency is required')
      }
      const channels = draftsToChannels(edit.channelDrafts)
      if (!Object.keys(channels).length) {
        throw new Error('Add at least one channel (amazon / shopify / …)')
      }
      const defaultChannel = (edit.default_channel || Object.keys(channels)[0]).toLowerCase()
      if (!channels[defaultChannel]) {
        throw new Error(`default_channel "${defaultChannel}" must exist in channels`)
      }
      return api.configSaveGeography(
        edit.client,
        code,
        {
          country_code: code,
          country_currency: edit.country_currency.trim(),
          enabled: edit.enabled,
          default_channel: defaultChannel,
          channels,
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
      toast.push({
        kind: 'error',
        title: 'Save failed',
        description: e instanceof Error ? e.message : undefined,
      }),
  })

  const filtered = useMemo(() => {
    return (geos.data ?? []).filter((g) => {
      if (!q) return true
      const s = q.toLowerCase()
      return (
        g.country_code.toLowerCase().includes(s) ||
        (g.default_channel || '').toLowerCase().includes(s) ||
        channelSearchText(g).toLowerCase().includes(s) ||
        (g.country_currency || '').toLowerCase().includes(s)
      )
    })
  }, [geos.data, q])

  if (clients.isLoading) return <Spinner />
  if (clients.error) {
    return (
      <ErrorState
        title="Unable to load clients"
        onRetry={() => void clients.refetch()}
      />
    )
  }
  if (!client) return <EmptyState title="No clients configured" />

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Geographies"
          description="geo × channel → cogs/{client}/{geo}_{channel}_cogs.* · markets/vendors for Shopify · orders_sales_channel for Amazon"
          action={
            <Button onClick={() => setEdit(emptyDraft(client))}>Add geography</Button>
          }
        />
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-3">
          {(clients.data ?? []).map((c) => (
            <Button
              key={c.code}
              variant={client === c.code ? 'primary' : 'ghost'}
              onClick={() => {
                setClient(c.code)
                setEdit(null)
              }}
            >
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
        {geos.isLoading ? (
          <Spinner />
        ) : geos.error ? (
          <ErrorState title="Unable to load geographies" onRetry={() => void geos.refetch()} />
        ) : filtered.length === 0 ? (
          <EmptyState title={`No geographies for ${client}`} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] uppercase text-[var(--fg-muted)]">
                <tr>
                  <th className="px-5 py-2">Code</th>
                  <th className="px-5 py-2">Currency</th>
                  <th className="px-5 py-2">Default channel</th>
                  <th className="px-5 py-2">Channels</th>
                  <th className="px-5 py-2">Status</th>
                  <th className="px-5 py-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filtered.map((g) => (
                  <tr key={`${g.client}-${g.country_code}`} className="align-top">
                    <td className="px-5 py-3 font-mono font-semibold">{g.country_code}</td>
                    <td className="px-5 py-3 font-mono text-xs">{g.country_currency}</td>
                    <td className="px-5 py-3 font-mono text-xs">
                      {g.default_channel || '—'}
                    </td>
                    <td className="px-5 py-2">
                      <ChannelsCell g={g} />
                    </td>
                    <td className="px-5 py-3">
                      <Badge tone={g.enabled ? 'ok' : 'warn'}>
                        {g.enabled ? 'enabled' : 'disabled'}
                      </Badge>
                    </td>
                    <td className="px-5 py-3">
                      <Button
                        variant="secondary"
                        onClick={() =>
                          setEdit({
                            ...g,
                            isNew: false,
                            channelDrafts: channelsToDrafts(g),
                          })
                        }
                      >
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
          <PanelHeader
            title={
              edit.isNew
                ? `Add geography · ${edit.client}`
                : `Edit ${edit.client}/${edit.country_code}`
            }
          />
          <div className="grid gap-3 p-5 sm:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Client</span>
              <select
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                value={edit.client}
                disabled={!edit.isNew}
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
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">
                Geo code (2 letters)
              </span>
              <input
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                value={edit.country_code}
                disabled={!edit.isNew}
                maxLength={2}
                placeholder="UK"
                onChange={(e) =>
                  setEdit({ ...edit, country_code: e.target.value.toUpperCase() })
                }
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">
                Currency
              </span>
              <input
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                value={edit.country_currency}
                placeholder="GBP"
                onChange={(e) => setEdit({ ...edit, country_currency: e.target.value })}
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">
                Default channel
              </span>
              <input
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                value={edit.default_channel || 'amazon'}
                placeholder="amazon"
                onChange={(e) =>
                  setEdit({ ...edit, default_channel: e.target.value.toLowerCase() })
                }
              />
            </label>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input
                type="checkbox"
                checked={edit.enabled}
                onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })}
              />
              Enabled
            </label>
          </div>

          <div className="border-t border-[var(--border)] px-5 py-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium">Channels</p>
                <p className="text-[11px] text-[var(--fg-muted)]">
                  Local COGS = cogs/{edit.client.toLowerCase()}/
                  {(edit.country_code || 'xx').toLowerCase()}
                  _{'{channel}'}_cogs.* · excel_sheet is upload-only · Shopify uses markets +
                  vendors · Amazon uses orders_sales_channel
                </p>
              </div>
              <Button
                variant="secondary"
                onClick={() =>
                  setEdit({
                    ...edit,
                    channelDrafts: [
                      ...edit.channelDrafts,
                      {
                        name: 'shopify',
                        excel_sheet: '',
                        orders_sales_channel: '',
                        markets: '',
                        vendors: '',
                      },
                    ],
                  })
                }
              >
                Add channel
              </Button>
            </div>

            <div className="space-y-4">
              {edit.channelDrafts.map((ch, idx) => (
                <div
                  key={idx}
                  className="rounded-md border border-[var(--border)] bg-[var(--bg)] p-4"
                >
                  <div className="mb-3 flex items-center justify-between">
                    <p className="font-mono text-xs uppercase text-[var(--fg-muted)]">
                      Channel {idx + 1}
                      {edit.country_code
                        ? ` → ${edit.client.toLowerCase()}/${edit.country_code.toLowerCase()}_${(ch.name || 'channel').toLowerCase()}_cogs`
                        : ''}
                    </p>
                    {edit.channelDrafts.length > 1 ? (
                      <Button
                        variant="ghost"
                        onClick={() =>
                          setEdit({
                            ...edit,
                            channelDrafts: edit.channelDrafts.filter((_, i) => i !== idx),
                          })
                        }
                      >
                        Remove
                      </Button>
                    ) : null}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="space-y-1 text-sm">
                      <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">
                        Name (amazon / shopify)
                      </span>
                      <input
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2 font-mono"
                        value={ch.name}
                        onChange={(e) => {
                          const next = [...edit.channelDrafts]
                          next[idx] = { ...ch, name: e.target.value.toLowerCase() }
                          setEdit({ ...edit, channelDrafts: next })
                        }}
                      />
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">
                        excel_sheet (upload only)
                      </span>
                      <input
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2"
                        value={ch.excel_sheet}
                        placeholder="Main / Shopify / ESH-UK"
                        onChange={(e) => {
                          const next = [...edit.channelDrafts]
                          next[idx] = { ...ch, excel_sheet: e.target.value }
                          setEdit({ ...edit, channelDrafts: next })
                        }}
                      />
                    </label>
                    <label className="space-y-1 text-sm sm:col-span-2">
                      <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">
                        orders_sales_channel (Amazon filter)
                      </span>
                      <input
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2"
                        value={ch.orders_sales_channel}
                        placeholder="Amazon.co.uk"
                        onChange={(e) => {
                          const next = [...edit.channelDrafts]
                          next[idx] = { ...ch, orders_sales_channel: e.target.value }
                          setEdit({ ...edit, channelDrafts: next })
                        }}
                      />
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">
                        markets (Shopify, comma-separated)
                      </span>
                      <input
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2"
                        value={ch.markets}
                        placeholder="United Kingdom"
                        onChange={(e) => {
                          const next = [...edit.channelDrafts]
                          next[idx] = { ...ch, markets: e.target.value }
                          setEdit({ ...edit, channelDrafts: next })
                        }}
                      />
                    </label>
                    <label className="space-y-1 text-sm">
                      <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">
                        vendors (Shopify, comma-separated)
                      </span>
                      <input
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-2"
                        value={ch.vendors}
                        placeholder="Kinetica - UK, Kinetica Sports UK"
                        onChange={(e) => {
                          const next = [...edit.channelDrafts]
                          next[idx] = { ...ch, vendors: e.target.value }
                          setEdit({ ...edit, channelDrafts: next })
                        }}
                      />
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex gap-2 border-t border-[var(--border)] px-5 py-3">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              Save to geography.yaml
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
