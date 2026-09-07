import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Download, ExternalLink, FolderOpen } from 'lucide-react'
import { useClients } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import type { FilePreview, ReportOutputFolder } from '@/types'

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function OutputsPage() {
  const toast = useToast()
  const clients = useClients()
  const [client, setClient] = useState<string>('')
  const [selected, setSelected] = useState<ReportOutputFolder | null>(null)
  const [preview, setPreview] = useState<FilePreview | null>(null)

  const outputs = useQuery({
    queryKey: ['explore-outputs', client || 'all'],
    queryFn: () => api.exploreOutputs(client ? { client } : undefined),
  })

  const visible = useMemo(() => outputs.data ?? [], [outputs.data])

  if (clients.isLoading || outputs.isLoading) return <Spinner label="Loading outputs…" />
  if (outputs.error) {
    return (
      <ErrorState
        title="Unable to load outputs"
        message={outputs.error instanceof Error ? outputs.error.message : undefined}
        onRetry={() => void outputs.refetch()}
      />
    )
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Outputs"
          description="sanity_data/{CLIENT}/{output_subdir}/ — path links from report.yaml (no full parquet load)"
        />
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-3">
          <Button variant={!client ? 'primary' : 'secondary'} onClick={() => setClient('')}>
            All clients
          </Button>
          {(clients.data ?? []).map((c) => (
            <Button
              key={c.code}
              variant={client === c.code ? 'primary' : 'ghost'}
              onClick={() => setClient(c.code)}
            >
              {c.code}
            </Button>
          ))}
        </div>

        {visible.length === 0 ? (
          <EmptyState
            title="No output folders registered"
            description="Reports need output_subdir in report.yaml. Run a pipeline to create files under sanity_data/."
          />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {visible.map((row) => (
              <div
                key={`${row.client}-${row.report}`}
                className="flex flex-wrap items-start justify-between gap-3 px-5 py-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">{row.client}</span>
                    <Badge tone="accent">{row.report}</Badge>
                    <Badge tone={row.exists ? 'ok' : 'warn'}>
                      {row.exists ? `${row.file_count} files` : 'missing'}
                    </Badge>
                  </div>
                  <p className="mt-1 text-sm">{row.label}</p>
                  <p className="mt-1 break-all font-mono text-[11px] text-[var(--fg-muted)]">
                    {row.path}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      void navigator.clipboard.writeText(row.path)
                      toast.push({ kind: 'info', title: 'Path copied' })
                    }}
                  >
                    <Copy className="h-4 w-4" />
                    Copy path
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setSelected(row)
                      setPreview(null)
                    }}
                  >
                    <FolderOpen className="h-4 w-4" />
                    Files
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {selected ? (
        <Panel>
          <PanelHeader
            title={`${selected.client} / ${selected.report}`}
            description={selected.path}
            action={
              <Button variant="ghost" onClick={() => setSelected(null)}>
                Close
              </Button>
            }
          />
          {selected.files.length === 0 ? (
            <EmptyState title="Folder empty or missing" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="border-b border-[var(--border)] text-[11px] uppercase text-[var(--fg-muted)]">
                  <tr>
                    <th className="px-5 py-2">File</th>
                    <th className="px-5 py-2">Geo</th>
                    <th className="px-5 py-2">Size</th>
                    <th className="px-5 py-2">Modified</th>
                    <th className="px-5 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {selected.files.map((f) => {
                    const rel = `${selected.rel}/${f.name}`
                    return (
                      <tr key={f.name}>
                        <td className="px-5 py-2 font-mono text-xs">{f.name}</td>
                        <td className="px-5 py-2 font-mono text-xs">{f.geo ?? '—'}</td>
                        <td className="px-5 py-2 font-mono text-xs">{formatBytes(f.size_bytes)}</td>
                        <td className="px-5 py-2 font-mono text-[11px] text-[var(--fg-muted)]">
                          {f.modified?.slice(0, 19) ?? '—'}
                        </td>
                        <td className="px-5 py-2">
                          <div className="flex gap-2">
                            <Button
                              variant="secondary"
                              onClick={async () => {
                                try {
                                  setPreview(await api.explorePreview('sanity', rel))
                                } catch (err) {
                                  toast.push({
                                    kind: 'error',
                                    title: 'Preview failed',
                                    description: err instanceof Error ? err.message : undefined,
                                  })
                                }
                              }}
                            >
                              <ExternalLink className="h-4 w-4" />
                              Preview
                            </Button>
                            <a href={api.exploreDownloadUrl('sanity', rel)}>
                              <Button variant="ghost">
                                <Download className="h-4 w-4" />
                                Download
                              </Button>
                            </a>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ) : null}

      {preview ? (
        <Panel>
          <PanelHeader
            title={`Preview · ${preview.file.name}`}
            description={preview.path}
            action={
              <Button variant="ghost" onClick={() => setPreview(null)}>
                Close
              </Button>
            }
          />
          <div className="p-5">
            {preview.preview.note && preview.preview.note !== 'text' ? (
              <p className="text-sm text-[var(--fg-muted)]">{preview.preview.note}</p>
            ) : null}
            {preview.preview.text ? (
              <pre className="max-h-96 overflow-auto rounded-md border border-[var(--border)] bg-[var(--bg)] p-3 font-mono text-xs">
                {preview.preview.text}
              </pre>
            ) : null}
            {preview.preview.rows && preview.preview.rows.length > 0 ? (
              <div className="overflow-x-auto">
                <p className="mb-2 font-mono text-xs text-[var(--fg-muted)]">
                  Showing {preview.preview.rows.length}
                  {preview.preview.row_count != null ? ` of ${preview.preview.row_count}` : ''} rows
                </p>
                <table className="w-full min-w-[480px] text-left text-xs">
                  <thead className="border-b border-[var(--border)] text-[var(--fg-muted)]">
                    <tr>
                      {(preview.preview.columns ?? Object.keys(preview.preview.rows[0] ?? {})).map(
                        (c) => (
                          <th key={c} className="px-2 py-1 font-mono font-medium">
                            {c}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {preview.preview.rows.map((row, i) => (
                      <tr key={i}>
                        {(preview.preview.columns ?? Object.keys(row)).map((c) => (
                          <td key={c} className="max-w-[180px] truncate px-2 py-1 font-mono">
                            {String(row[c] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        </Panel>
      ) : null}
    </div>
  )
}
