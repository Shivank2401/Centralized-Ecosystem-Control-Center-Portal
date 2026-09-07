import { useStages } from '@/hooks/useApi'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { formatStageLabel } from '@/utils/cn'

export function StagesPage() {
  const stages = useStages()
  if (stages.isLoading) return <Spinner />
  if (stages.error) {
    return (
      <ErrorState
        title="Unable to load stages"
        message={stages.error instanceof Error ? stages.error.message : undefined}
        onRetry={() => void stages.refetch()}
      />
    )
  }
  const list = stages.data ?? []
  return (
    <Panel className="mx-auto max-w-3xl">
      <PanelHeader title="Stages" description="report_stages from report.yaml" />
      {list.length === 0 ? (
        <EmptyState title="No stages" />
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {list.map((s) => (
            <li key={s.key} className="flex items-start justify-between gap-4 px-5 py-3">
              <div>
                <p className="font-medium">{formatStageLabel(s.label)}</p>
                <p className="font-mono text-xs text-[var(--fg-muted)]">{s.key}</p>
                {s.package_path ? (
                  <p className="mt-1 font-mono text-[11px] text-[var(--fg-muted)]">
                    {s.package_path}
                  </p>
                ) : null}
              </div>
              <span className="font-mono text-xs text-[var(--fg-muted)]">#{s.order ?? '—'}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
