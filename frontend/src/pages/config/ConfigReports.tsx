import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FolderCode } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { api } from '@/services/api'
import { formatStageLabel } from '@/utils/cn'
import type { ReportScriptPackage } from '@/types/reportScripts'

function packageTitle(pkg: ReportScriptPackage) {
  if (pkg.stage_label) return formatStageLabel(pkg.stage_label)
  return pkg.name.replace(/_/g, ' ')
}

/** Configuration → Reports: browse report_script/ packages (same layout as former Script packages). */
export function ConfigReportsPage() {
  const q = useQuery({
    queryKey: ['report-script-packages'],
    queryFn: api.reportScriptPackages,
  })

  if (q.isLoading) return <Spinner label="Scanning report_script…" />
  if (q.error) {
    return (
      <ErrorState
        title="Unable to load script packages"
        message={q.error instanceof Error ? q.error.message : undefined}
        onRetry={() => void q.refetch()}
      />
    )
  }

  const packages = q.data ?? []

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Reports"
          description="Browse folders under report_script/"
        />
        {packages.length === 0 ? (
          <EmptyState title="No packages found" description="report_script/ has no folders yet." />
        ) : (
          <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {packages.map((pkg) => (
              <Link
                key={pkg.name}
                to={`/config/reports/${encodeURIComponent(pkg.name)}`}
                className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4 transition hover:border-[var(--accent)]"
              >
                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[var(--accent-soft)] text-[var(--accent)]">
                    <FolderCode className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold capitalize">{packageTitle(pkg)}</p>
                    <p className="mt-0.5 font-mono text-[11px] text-[var(--fg-muted)]">{pkg.path}</p>
                    <p className="mt-2 text-xs text-[var(--fg-muted)]">
                      {pkg.script_count} scripts · {pkg.registered_count} registered
                    </p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}

export function ConfigReportPackagePage() {
  const { packageName } = useParams()
  const name = packageName ? decodeURIComponent(packageName) : ''
  const q = useQuery({
    queryKey: ['report-script-package', name],
    queryFn: () => api.reportScriptPackage(name),
    enabled: Boolean(name),
  })

  if (!name) return <EmptyState title="Missing package" />
  if (q.isLoading) return <Spinner label={`Loading ${name}…`} />
  if (q.error) {
    return (
      <ErrorState
        title="Unable to load package"
        message={q.error instanceof Error ? q.error.message : undefined}
        onRetry={() => void q.refetch()}
      />
    )
  }

  const pkg = q.data!
  const title = packageTitle(pkg)

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title={title}
          description={`${pkg.path} · ${pkg.script_count} Python files`}
          action={
            <Link to="/config/reports">
              <Button variant="ghost">All packages</Button>
            </Link>
          }
        />
        {pkg.scripts.length === 0 ? (
          <EmptyState title="No scripts in this folder" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-[var(--border)] text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">
                <tr>
                  <th className="px-5 py-3 font-medium">Script</th>
                  <th className="px-5 py-3 font-medium">Module</th>
                  <th className="px-5 py-3 font-medium">Clients</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {pkg.scripts.map((s) => (
                  <tr key={s.file} className="hover:bg-[var(--accent-soft)]/40">
                    <td className="px-5 py-3">
                      <p className="font-medium">{s.label}</p>
                      <p className="font-mono text-xs text-[var(--fg-muted)]">{s.file}</p>
                      {s.report_code ? (
                        <p className="mt-0.5 font-mono text-[10px] text-[var(--fg-muted)]">
                          report · {s.report_code}
                        </p>
                      ) : null}
                    </td>
                    <td className="max-w-[280px] truncate px-5 py-3 font-mono text-[11px] text-[var(--fg-muted)]">
                      {s.module}
                    </td>
                    <td className="px-5 py-3 text-xs">
                      {s.clients?.length ? s.clients.join(', ') : s.registered ? 'All' : '—'}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap gap-1">
                        {s.registered && s.enabled ? <Badge tone="ok">registered</Badge> : null}
                        {s.registered && !s.enabled ? <Badge tone="warn">disabled</Badge> : null}
                        {!s.registered ? <Badge tone="neutral">not registered</Badge> : null}
                        {s.has_run ? <Badge tone="accent">run()</Badge> : null}
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
