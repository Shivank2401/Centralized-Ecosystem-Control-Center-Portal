import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Download } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import type { BrowseResult } from '@/types'

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function CogsPage() {
  const toast = useToast()
  const [client, setClient] = useState('')
  const q = useQuery({
    queryKey: ['explore-cogs', client || 'root'],
    queryFn: async () => {
      if (!client) {
        const raw = (await api.exploreCogs()) as {
          exists: boolean
          path: string
          clients: string[]
          listing: BrowseResult
        }
        return raw
      }
      const listing = (await api.exploreCogs(client)) as BrowseResult
      return { exists: listing.exists, path: listing.path, clients: [] as string[], listing }
    },
  })

  if (q.isLoading) return <Spinner />
  if (q.error) {
    return (
      <ErrorState
        title="Unable to load COGS"
        message={q.error instanceof Error ? q.error.message : undefined}
        onRetry={() => void q.refetch()}
      />
    )
  }

  const data = q.data!

  return (
    <div className="mx-auto max-w-5xl">
      <Panel>
        <PanelHeader
          title="COGS"
          description="Local slices under cogs/{client}/ — parquet/csv path links"
        />
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-3">
          <Button variant={!client ? 'primary' : 'secondary'} onClick={() => setClient('')}>
            Root
          </Button>
          {(data.clients.length
            ? data.clients
            : data.listing.directories.map((d) => d.name)
          ).map((c) => (
            <Button
              key={c}
              variant={client === c ? 'primary' : 'ghost'}
              onClick={() => setClient(c)}
            >
              {c}
            </Button>
          ))}
        </div>
        <p className="break-all px-5 py-2 font-mono text-[11px] text-[var(--fg-muted)]">{data.path}</p>
        {!data.exists ? (
          <EmptyState title="COGS folder missing" description={data.path} />
        ) : (
          <FileTable
            root="cogs"
            files={data.listing.files}
            dirs={data.listing.directories}
            onCopy={(p) => {
              void navigator.clipboard.writeText(p)
              toast.push({ kind: 'info', title: 'Path copied' })
            }}
            onOpenDir={(name) => setClient(name)}
          />
        )}
      </Panel>
    </div>
  )
}

export function PincodePage() {
  const toast = useToast()
  const q = useQuery({ queryKey: ['explore-pincode'], queryFn: api.explorePincode })
  if (q.isLoading) return <Spinner />
  if (q.error) {
    return (
      <ErrorState
        title="Unable to load pincode data"
        message={q.error instanceof Error ? q.error.message : undefined}
        onRetry={() => void q.refetch()}
      />
    )
  }
  const data = q.data!
  return (
    <div className="mx-auto max-w-5xl">
      <Panel>
        <PanelHeader
          title="Pincode"
          description="{geo}_amazon_pincode.csv under PINCODE_DATA_DIR / project pincode/"
        />
        <p className="break-all border-b border-[var(--border)] px-5 py-2 font-mono text-[11px] text-[var(--fg-muted)]">
          {data.path}
        </p>
        {!data.exists ? (
          <EmptyState title="Pincode folder missing" />
        ) : (
          <FileTable
            root="pincode"
            files={data.files}
            dirs={data.directories}
            onCopy={(p) => {
              void navigator.clipboard.writeText(p)
              toast.push({ kind: 'info', title: 'Path copied' })
            }}
          />
        )}
      </Panel>
    </div>
  )
}

function FileTable({
  root,
  files,
  dirs,
  onCopy,
  onOpenDir,
}: {
  root: string
  files: BrowseResult['files']
  dirs: BrowseResult['directories']
  onCopy: (path: string) => void
  onOpenDir?: (name: string) => void
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="border-b border-[var(--border)] text-[11px] uppercase text-[var(--fg-muted)]">
          <tr>
            <th className="px-5 py-2">Name</th>
            <th className="px-5 py-2">Type</th>
            <th className="px-5 py-2">Size</th>
            <th className="px-5 py-2">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)]">
          {dirs.map((d) => (
            <tr key={d.rel}>
              <td className="px-5 py-2 font-mono text-xs">{d.name}/</td>
              <td className="px-5 py-2">
                <Badge>dir</Badge>
              </td>
              <td className="px-5 py-2">—</td>
              <td className="px-5 py-2">
                <div className="flex gap-2">
                  {onOpenDir ? (
                    <Button variant="secondary" onClick={() => onOpenDir(d.name)}>
                      Open
                    </Button>
                  ) : null}
                  <Button variant="ghost" onClick={() => onCopy(d.path)}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </td>
            </tr>
          ))}
          {files.map((f) => (
            <tr key={f.rel}>
              <td className="px-5 py-2 font-mono text-xs">{f.name}</td>
              <td className="px-5 py-2">
                <Badge tone="accent">{f.kind}</Badge>
              </td>
              <td className="px-5 py-2 font-mono text-xs">{formatBytes(f.size_bytes)}</td>
              <td className="px-5 py-2">
                <div className="flex gap-2">
                  <a href={api.exploreDownloadUrl(root, f.rel)}>
                    <Button variant="secondary">
                      <Download className="h-4 w-4" />
                    </Button>
                  </a>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {dirs.length === 0 && files.length === 0 ? (
        <EmptyState title="Empty folder" />
      ) : null}
    </div>
  )
}
