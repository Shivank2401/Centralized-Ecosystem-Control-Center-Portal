import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useReports } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'

export function ReportRegistryPage() {
  const reports = useReports({ enabledOnly: false })
  const toast = useToast()
  const qc = useQueryClient()

  const toggle = useMutation({
    mutationFn: ({ code, enabled }: { code: string; enabled: boolean }) =>
      api.setReportEnabled(code, enabled),
    onSuccess: (data) => {
      toast.push({
        kind: 'success',
        title: data.enabled ? 'Report enabled' : 'Report disabled',
        description: data.code,
      })
      void qc.invalidateQueries({ queryKey: ['reports'] })
    },
    onError: (err) => {
      toast.push({
        kind: 'error',
        title: 'Update failed',
        description: err instanceof Error ? err.message : undefined,
      })
    },
  })

  const testImport = useMutation({
    mutationFn: (code: string) => api.testReportImport(code),
    onSuccess: (data) => {
      toast.push({
        kind: data.import_ok ? 'success' : 'error',
        title: data.import_ok ? 'Import OK' : 'Import failed',
        description: data.error || data.module,
      })
    },
  })

  if (reports.isLoading) return <Spinner label="Loading registry…" />
  if (reports.error) {
    return (
      <ErrorState
        title="Unable to load registry"
        message={reports.error instanceof Error ? reports.error.message : undefined}
        onRetry={() => void reports.refetch()}
      />
    )
  }

  const list = reports.data ?? []

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Report Registry"
          description="Enable/disable entries in report.yaml · import smoke test (does not run ETL)"
          action={
            <Link to="/developer/add-report">
              <Button>Add Report</Button>
            </Link>
          }
        />
        {list.length === 0 ? (
          <EmptyState title="No reports registered" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">
                <tr>
                  <th className="px-5 py-3 font-medium">Report</th>
                  <th className="px-5 py-3 font-medium">Stage</th>
                  <th className="px-5 py-3 font-medium">Module</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {list.map((r) => (
                  <tr key={r.code}>
                    <td className="px-5 py-3">
                      <p className="font-medium">{r.label}</p>
                      <p className="font-mono text-xs text-[var(--fg-muted)]">{r.code}</p>
                    </td>
                    <td className="px-5 py-3 font-mono text-xs">{r.stage}</td>
                    <td className="max-w-[240px] truncate px-5 py-3 font-mono text-[11px] text-[var(--fg-muted)]">
                      {r.module}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-1">
                        <Badge tone={r.enabled ? 'ok' : 'warn'}>
                          {r.enabled ? 'enabled' : 'disabled'}
                        </Badge>
                        <Badge tone={r.module_importable ? 'accent' : 'danger'}>
                          {r.module_importable ? 'importable' : 'broken'}
                        </Badge>
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="secondary"
                          disabled={toggle.isPending}
                          onClick={() => toggle.mutate({ code: r.code, enabled: !r.enabled })}
                        >
                          {r.enabled ? 'Disable' : 'Enable'}
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={testImport.isPending}
                          onClick={() => testImport.mutate(r.code)}
                        >
                          Test import
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
    </div>
  )
}
