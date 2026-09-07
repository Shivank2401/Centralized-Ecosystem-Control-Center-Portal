import { Link } from 'react-router-dom'
import { useActiveRun } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { RunDetailPage } from '@/pages/RunDetail'

export function ActiveRunsPage() {
  const active = useActiveRun()

  if (active.isLoading) return <Spinner label="Checking active runs…" />
  if (active.error) {
    return (
      <ErrorState
        title="Unable to load active run"
        message={active.error instanceof Error ? active.error.message : undefined}
        onRetry={() => void active.refetch()}
      />
    )
  }

  if (!active.data) {
    return (
      <Panel className="mx-auto max-w-xl">
        <PanelHeader title="Pipeline idle" description="No run is queued or executing" />
        <EmptyState
          title="No active runs"
          description="Start a pipeline from the Run wizard. Only one run executes at a time."
          action={
            <Link to="/pipeline/run">
              <Button>Run Pipeline</Button>
            </Link>
          }
        />
      </Panel>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Badge tone="accent">active</Badge>
        <span className="font-mono text-sm text-[var(--fg-muted)]">{active.data.run_id}</span>
      </div>
      <RunDetailPage runId={active.data.run_id} />
    </div>
  )
}
