import { useState } from 'react'
import { useClients, useGeographies } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'

export function GeographiesPage() {
  const clients = useClients()
  const [client, setClient] = useState('ESH')
  const geos = useGeographies(client)

  if (clients.isLoading) return <Spinner />
  if (clients.error) {
    return (
      <ErrorState
        title="Unable to load clients"
        message={clients.error instanceof Error ? clients.error.message : undefined}
        onRetry={() => void clients.refetch()}
      />
    )
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {(clients.data ?? []).map((c) => (
          <Button
            key={c.code}
            variant={client === c.code ? 'primary' : 'secondary'}
            onClick={() => setClient(c.code)}
          >
            {c.code}
          </Button>
        ))}
      </div>
      <Panel>
        <PanelHeader title={`Geographies · ${client}`} description="From geography.yaml" />
        {geos.isLoading ? (
          <Spinner />
        ) : geos.error ? (
          <ErrorState
            title="Unable to load geographies"
            message={geos.error instanceof Error ? geos.error.message : undefined}
            onRetry={() => void geos.refetch()}
          />
        ) : (geos.data?.length ?? 0) === 0 ? (
          <EmptyState title="No geographies" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] text-[var(--fg-muted)] uppercase">
                <tr>
                  <th className="px-5 py-3">Geo</th>
                  <th className="px-5 py-3">Currency</th>
                  <th className="px-5 py-3">Channels / COGS stem</th>
                  <th className="px-5 py-3">Default sales channel</th>
                  <th className="px-5 py-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {(geos.data ?? []).map((g) => (
                  <tr key={g.country_code}>
                    <td className="px-5 py-3 font-mono font-semibold">{g.country_code}</td>
                    <td className="px-5 py-3">{g.country_currency}</td>
                    <td className="px-5 py-3 font-mono text-[11px] text-[var(--fg-muted)]">
                      {Object.keys(g.channels ?? {}).length
                        ? Object.entries(g.channels ?? {})
                            .map(([n, ch]) => `${n}→${ch.cogs_stem || n}`)
                            .join(', ')
                        : g.cogs_sheet_name || '—'}
                    </td>
                    <td className="px-5 py-3 text-[var(--fg-muted)]">
                      {g.orders_sales_channel || '—'}
                    </td>
                    <td className="px-5 py-3">
                      <Badge tone={g.enabled ? 'ok' : 'warn'}>
                        {g.enabled ? 'enabled' : 'disabled'}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
