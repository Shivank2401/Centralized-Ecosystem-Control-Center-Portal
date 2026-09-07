import { useClients } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'

export function ClientsPage() {
  const clients = useClients()
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
    <Panel className="mx-auto max-w-4xl">
      <PanelHeader title="Clients" description="From client.yaml — secrets never shown" />
      <div className="divide-y divide-[var(--border)]">
        {(clients.data ?? []).map((c) => (
          <div key={c.code} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
            <div>
              <p className="font-mono text-lg font-semibold">{c.code}</p>
              <p className="text-sm text-[var(--fg-muted)]">{c.name}</p>
              <p className="mt-1 font-mono text-xs text-[var(--fg-muted)]">
                env: {c.data_root_env} · {c.cogs_path_env}
              </p>
            </div>
            <div className="flex flex-col items-end gap-2">
              <Badge tone={c.enabled ? 'ok' : 'warn'}>{c.enabled ? 'enabled' : 'disabled'}</Badge>
              <p className="font-mono text-xs text-[var(--fg-muted)]">{c.geographies.join(' · ')}</p>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}
