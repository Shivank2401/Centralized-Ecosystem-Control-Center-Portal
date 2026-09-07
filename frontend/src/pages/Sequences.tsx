import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Play } from 'lucide-react'
import { useSequences } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api, ApiError } from '@/services/api'

export function SequencesPage() {
  const sequences = useSequences()
  const navigate = useNavigate()
  const toast = useToast()
  const qc = useQueryClient()

  const runSeq = useMutation({
    mutationFn: (id: string) => api.runSequence(id),
    onSuccess: (run) => {
      toast.push({ kind: 'success', title: 'Sequence started', description: run.run_id })
      void qc.invalidateQueries({ queryKey: ['runs'] })
      navigate(`/pipeline/runs/${run.run_id}`)
    },
    onError: (err) => {
      const busy = err instanceof ApiError && err.code === 'PIPELINE_BUSY'
      toast.push({
        kind: 'error',
        title: busy ? 'Pipeline busy' : 'Failed to start sequence',
        description: err instanceof Error ? err.message : undefined,
      })
    },
  })

  if (sequences.isLoading) return <Spinner />
  if (sequences.error) {
    return (
      <ErrorState
        title="Unable to load sequences"
        message={sequences.error instanceof Error ? sequences.error.message : undefined}
        onRetry={() => void sequences.refetch()}
      />
    )
  }

  const list = sequences.data ?? []
  return (
    <Panel className="mx-auto max-w-4xl">
      <PanelHeader
        title="Saved Sequences"
        description="config_manager/run_sequences.yaml — run starts the same worker as the wizard"
      />
      {list.length === 0 ? (
        <EmptyState title="No sequences saved" description="Create one via CLI for now." />
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {list.map((seq) => (
            <div key={seq.id} className="px-5 py-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold">{seq.label}</h3>
                <div className="flex items-center gap-2">
                  <Badge tone="accent">{seq.id}</Badge>
                  <Button
                    onClick={() => runSeq.mutate(seq.id)}
                    disabled={runSeq.isPending}
                  >
                    <Play className="h-4 w-4" />
                    Run
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() =>
                      navigate('/pipeline/run', {
                        state: {
                          clients: seq.clients,
                          geos: seq.geos,
                          reports: seq.reports,
                        },
                      })
                    }
                  >
                    Open in wizard
                  </Button>
                </div>
              </div>
              <p className="mt-1 font-mono text-xs text-[var(--fg-muted)]">
                {seq.clients.join(', ')} · {seq.geos.join(', ')}
              </p>
              <ol className="mt-3 space-y-1 font-mono text-xs">
                {seq.reports.map((r, i) => (
                  <li key={`${seq.id}-${r}-${i}`}>
                    {i + 1}. {r}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
