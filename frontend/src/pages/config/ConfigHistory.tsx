import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'

type Hist = {
  id: string
  timestamp: string
  user: string
  file: string
  action: string
  summary: string
  diff?: string
  backup?: string
}

export function ConfigHistoryPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const history = useQuery({ queryKey: ['config-history'], queryFn: () => api.configHistory(100) })
  const [selected, setSelected] = useState<Hist | null>(null)

  const restore = useMutation({
    mutationFn: (id: string) => api.configRestoreHistory(id),
    onSuccess: () => {
      toast.push({ kind: 'success', title: 'Configuration restored' })
      void qc.invalidateQueries({ queryKey: ['config-history'] })
      void qc.invalidateQueries({ queryKey: ['config-overview'] })
      void qc.invalidateQueries({ queryKey: ['config-files'] })
      setSelected(null)
    },
    onError: (e) =>
      toast.push({ kind: 'error', title: 'Restore failed', description: e instanceof Error ? e.message : undefined }),
  })

  if (history.isLoading) return <Spinner />
  if (history.error) return <ErrorState title="Unable to load history" onRetry={() => void history.refetch()} />

  const rows = (history.data ?? []) as Hist[]

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Configuration History"
          description="Backups under runtime/config_backups/ · local identity"
        />
        {rows.length === 0 ? (
          <EmptyState title="No history yet" description="Edits via the Configuration Center appear here." />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {rows.map((h) => (
              <div key={h.id} className="flex flex-wrap items-start justify-between gap-3 px-5 py-3">
                <div>
                  <p className="font-mono text-xs text-[var(--fg-muted)]">
                    {h.timestamp} · {h.user}
                  </p>
                  <p className="mt-1 text-sm">
                    <Badge tone="accent">{h.file}</Badge>{' '}
                    <span className="font-medium">{h.summary}</span>
                  </p>
                  <p className="mt-0.5 font-mono text-[11px] text-[var(--fg-muted)]">{h.action}</p>
                </div>
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setSelected(h)}>
                    View Diff
                  </Button>
                  {h.backup ? (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        if (window.confirm(`Restore ${h.file} from backup ${h.backup}?`)) {
                          restore.mutate(h.id)
                        }
                      }}
                    >
                      Restore
                    </Button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {selected ? (
        <Panel>
          <PanelHeader
            title={`Diff · ${selected.file}`}
            description={selected.summary}
            action={
              <Button variant="ghost" onClick={() => setSelected(null)}>
                Close
              </Button>
            }
          />
          <pre className="max-h-[28rem] overflow-auto border-t border-[var(--border)] bg-[var(--bg)] p-4 font-mono text-xs whitespace-pre-wrap">
            {selected.diff || '(no diff stored)'}
          </pre>
        </Panel>
      ) : null}
    </div>
  )
}
