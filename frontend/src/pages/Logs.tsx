import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'
import { useClients } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Modal } from '@/components/ui/Modal'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import type { LogContent, LogReportEntry } from '@/types'

function formatLogDateTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function lastRunIso(entry: LogReportEntry): string {
  return entry.latest_modified || entry.latest?.modified || entry.files[0]?.modified || ''
}

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
    list.sort((a, b) => lastRunIso(b).localeCompare(lastRunIso(a)))
    return list
  }, [logs.data])

  function closeModal() {
    setActive(null)
    setContent(null)
  }

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
          description="sanity_data/{CLIENT}/logs/{report}/ — newest runs first; each report keeps latest.log plus dated run snapshots"
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
            {reports.map((r) => {
              const runAt = lastRunIso(r)
              return (
                <div
                  key={`${r.client}-${r.report}`}
                  className="flex items-start justify-between gap-3 px-5 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-semibold">{r.client}</span>
                      <Badge tone="accent">{r.report}</Badge>
                      <span
                        title="Number of log files saved for this report (latest.log + dated YYYYMMDD_HHMMSS.log snapshots from past runs)"
                      >
                        <Badge tone="neutral">
                          {r.file_count} saved log{r.file_count === 1 ? '' : 's'}
                        </Badge>
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-[var(--fg)]">
                      Last run:{' '}
                      <span className="font-mono text-[var(--accent)]">{formatLogDateTime(runAt)}</span>
                    </p>
                    <p className="mt-0.5 break-all font-mono text-[11px] text-[var(--fg-muted)]">
                      {r.path}
                    </p>
                  </div>
                  <div className="shrink-0">
                    <Button onClick={() => void openLog(r)}>
                      <FileText className="h-4 w-4" />
                      View latest
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Panel>

      <Modal
        open={Boolean(active)}
        onClose={closeModal}
        labelledBy="log-viewer-title"
        title={active ? `${active.client} · ${active.report}` : 'Log'}
        description={active ? `Last run: ${formatLogDateTime(lastRunIso(active))}` : undefined}
        path={content?.path || active?.path}
        toolbar={
          active
            ? active.files.map((f) => (
                <Button
                  key={f.name}
                  variant={content?.filename === f.name ? 'primary' : 'ghost'}
                  onClick={() => void openLog(active, f.name)}
                  title={formatLogDateTime(f.modified)}
                >
                  <span className="flex flex-col items-start leading-tight">
                    <span>{f.name}</span>
                    <span className="text-[10px] opacity-80">{formatLogDateTime(f.modified)}</span>
                  </span>
                </Button>
              ))
            : null
        }
      >
        <div className="p-5">
          {loadingContent ? (
            <Spinner label="Reading log…" />
          ) : content ? (
            <>
              {content.truncated ? (
                <p className="mb-2 text-xs text-[var(--color-warn)]">
                  Truncated preview (file {content.size_bytes} bytes)
                </p>
              ) : null}
              <pre className="max-h-[min(60vh,32rem)] overflow-auto rounded-md border border-[var(--border)] bg-[var(--bg)] p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                {content.text || '(empty)'}
              </pre>
            </>
          ) : (
            <EmptyState title="No log content" />
          )}
        </div>
      </Modal>
    </div>
  )
}
