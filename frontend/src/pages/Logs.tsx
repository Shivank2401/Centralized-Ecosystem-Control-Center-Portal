import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, FileText } from 'lucide-react'
import { useClients } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import type { LogContent, LogReportEntry } from '@/types'

export function LogsPage() {
  const toast = useToast()
  const clients = useClients()
  const [client, setClient] = useState<string>('')
  const [active, setActive] = useState<LogReportEntry | null>(null)
  const [content, setContent] = useState<LogContent | null>(null)
  const [loadingContent, setLoadingContent] = useState(false)

  const logs = useQuery({
    queryKey: ['explore-logs', client || 'all'],
    queryFn: () => api.exploreLogs(client || undefined),
  })

  const reports = useMemo(() => {
    const list: LogReportEntry[] = []
    for (const block of logs.data ?? []) {
      for (const r of block.reports) list.push(r)
    }
    return list
  }, [logs.data])

  async function openLog(entry: LogReportEntry, filename = 'latest.log') {
    setActive(entry)
    setLoadingContent(true)
    try {
      const file = entry.files.some((f) => f.name === filename)
        ? filename
        : entry.files[0]?.name || filename
      setContent(await api.exploreLogContent(entry.client, entry.report, file))
    } catch (err) {
      setContent(null)
      toast.push({
        kind: 'error',
        title: 'Unable to read log',
        description: err instanceof Error ? err.message : undefined,
      })
    } finally {
      setLoadingContent(false)
    }
  }

  if (clients.isLoading || logs.isLoading) return <Spinner label="Loading report logs…" />
  if (logs.error) {
    return (
      <ErrorState
        title="Unable to load logs"
        message={logs.error instanceof Error ? logs.error.message : undefined}
        onRetry={() => void logs.refetch()}
      />
    )
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Report Logs"
          description="sanity_data/{CLIENT}/logs/{report}/ — client-specific, report-wise text logs"
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

        {reports.length === 0 ? (
          <EmptyState
            title="No report logs found"
            description="Common sanity reports write latest.log under sanity_data/{CLIENT}/logs/{report}/ after a run."
          />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {reports.map((r) => (
              <div
                key={`${r.client}-${r.report}`}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">{r.client}</span>
                    <Badge tone="accent">{r.report}</Badge>
                    <Badge tone="neutral">{r.file_count} files</Badge>
                  </div>
                  <p className="mt-1 break-all font-mono text-[11px] text-[var(--fg-muted)]">
                    {r.path}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      void navigator.clipboard.writeText(r.path)
                      toast.push({ kind: 'info', title: 'Path copied' })
                    }}
                  >
                    <Copy className="h-4 w-4" />
                    Copy path
                  </Button>
                  <Button onClick={() => void openLog(r)}>
                    <FileText className="h-4 w-4" />
                    View latest
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {active ? (
        <Panel>
          <PanelHeader
            title={`${active.client} · ${active.report}`}
            description={content?.path || active.path}
            action={
              <div className="flex flex-wrap gap-2">
                {active.files.map((f) => (
                  <Button
                    key={f.name}
                    variant={content?.filename === f.name ? 'primary' : 'ghost'}
                    onClick={() => void openLog(active, f.name)}
                  >
                    {f.name}
                  </Button>
                ))}
                <Button
                  variant="ghost"
                  onClick={() => {
                    setActive(null)
                    setContent(null)
                  }}
                >
                  Close
                </Button>
              </div>
            }
          />
          {loadingContent ? (
            <Spinner label="Reading log…" />
          ) : content ? (
            <div className="p-5">
              {content.truncated ? (
                <p className="mb-2 text-xs text-[var(--color-warn)]">
                  Truncated preview (file {content.size_bytes} bytes)
                </p>
              ) : null}
              <pre className="max-h-[32rem] overflow-auto rounded-md border border-[var(--border)] bg-[var(--bg)] p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                {content.text || '(empty)'}
              </pre>
            </div>
          ) : (
            <EmptyState title="No log content" />
          )}
        </Panel>
      ) : null}
    </div>
  )
}
