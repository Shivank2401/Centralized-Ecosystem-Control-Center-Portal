import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CloudUpload, FolderOpen, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { ApiError, api } from '@/services/api'

const ALLOWED = ['.csv', '.parquet', '.xlsx', '.xls', '.tsv', '.txt', '.json']

export function AzureUploadPage() {
  const toast = useToast()
  const [container, setContainer] = useState('esh')
  const [folderPath, setFolderPath] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [keepName, setKeepName] = useState(true)
  const [customName, setCustomName] = useState('')

  const containersQ = useQuery({
    queryKey: ['azure-containers'],
    queryFn: api.azureContainers,
  })

  const foldersQ = useQuery({
    queryKey: ['azure-folders', container, folderPath],
    queryFn: () => api.azureFolders(container, folderPath),
    enabled: Boolean(container),
  })

  const uploadMut = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('Select a file to upload')
      return api.azureUpload({
        file,
        container,
        blob_folder: folderPath,
        blob_name: keepName ? undefined : customName.trim() || undefined,
      })
    },
    onSuccess: (data) => {
      toast.push({
        kind: 'success',
        title: 'Uploaded to Azure',
        description: `${data.container_name}/${data.blob_path}`,
      })
      void foldersQ.refetch()
    },
    onError: (err) => {
      toast.push({
        kind: 'error',
        title: 'Upload failed',
        description: err instanceof ApiError || err instanceof Error ? err.message : String(err),
      })
    },
  })

  const containerMeta = useMemo(() => {
    const list = containersQ.data?.containers ?? []
    return list.find((c) => c.key === container)
  }, [containersQ.data, container])

  const sourceExt = file ? `.${file.name.split('.').pop()?.toLowerCase() ?? ''}` : ''
  const destPreview = keepName
    ? file?.name ?? '—'
    : customName.trim()
      ? customName.includes('.')
        ? customName.trim()
        : `${customName.trim()}${sourceExt}`
      : file?.name ?? '—'

  if (containersQ.isLoading) return <Spinner />
  if (containersQ.error) {
    return (
      <ErrorState
        title="Unable to load Azure containers"
        message={
          containersQ.error instanceof Error ? containersQ.error.message : undefined
        }
        onRetry={() => void containersQ.refetch()}
      />
    )
  }

  const containers = containersQ.data?.containers ?? []

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Panel>
        <PanelHeader
          title="Azure Upload"
          description="Export CSV / Parquet / Excel (and related) files to esh, knc, or emm containers"
        />

        <div className="space-y-5 px-5 py-4">
          {/* 1 — file */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">1. Select file</h3>
            <label className="flex cursor-pointer flex-col items-start gap-2 rounded-md border border-dashed border-[var(--border)] bg-[var(--bg-muted)]/40 px-4 py-5 hover:border-[var(--sidebar-primary)]">
              <span className="flex items-center gap-2 text-sm">
                <CloudUpload className="h-4 w-4" />
                {file ? file.name : 'Choose a file to upload'}
              </span>
              <span className="text-[11px] text-[var(--fg-muted)]">
                Allowed: {ALLOWED.join(', ')}
              </span>
              <input
                type="file"
                className="hidden"
                accept={ALLOWED.join(',')}
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null
                  setFile(f)
                  if (f && keepName) setCustomName('')
                }}
              />
            </label>
            {file ? (
              <p className="font-mono text-[11px] text-[var(--fg-muted)]">
                {(file.size / 1024).toFixed(1)} KB · {file.type || 'unknown type'}
              </p>
            ) : null}
          </section>

          {/* 2 — container */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">2. Container</h3>
            <div className="flex flex-wrap gap-2">
              {containers.map((c) => (
                <Button
                  key={c.key}
                  variant={container === c.key ? 'primary' : 'secondary'}
                  onClick={() => {
                    setContainer(c.key)
                    setFolderPath('')
                  }}
                >
                  {c.label}
                </Button>
              ))}
            </div>
            {containerMeta ? (
              <p className="break-all font-mono text-[11px] text-[var(--fg-muted)]">
                {containerMeta.container_name}{' '}
                <Badge tone="neutral">{containerMeta.env_var}</Badge>
              </p>
            ) : null}
          </section>

          {/* 3 — blob folder */}
          <section className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">3. Blob folder</h3>
              <Button
                variant="ghost"
                onClick={() => void foldersQ.refetch()}
                disabled={foldersQ.isFetching}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${foldersQ.isFetching ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
            </div>
            <input
              type="text"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value.replace(/\\/g, '/'))}
              placeholder="e.g. sanity_data/uploads (blank = container root)"
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm outline-none focus:border-[var(--sidebar-primary)]"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                variant={!folderPath ? 'primary' : 'ghost'}
                onClick={() => setFolderPath('')}
              >
                Root
              </Button>
              {(foldersQ.data?.folders ?? []).map((f) => (
                <Button
                  key={f.path}
                  variant={folderPath === f.path ? 'primary' : 'ghost'}
                  onClick={() => setFolderPath(f.path)}
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  {f.name}
                </Button>
              ))}
            </div>
            {foldersQ.isLoading ? (
              <p className="text-xs text-[var(--fg-muted)]">Loading folders…</p>
            ) : foldersQ.error ? (
              <p className="text-xs text-[var(--color-danger)]">
                {foldersQ.error instanceof Error
                  ? foldersQ.error.message
                  : 'Could not list folders'}
              </p>
            ) : (foldersQ.data?.folders.length ?? 0) === 0 ? (
              <EmptyState
                title="No folders at this level"
                description="Type a new folder path above — it will be created on upload."
              />
            ) : null}
          </section>

          {/* 4 — name */}
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">4. Destination name</h3>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={keepName}
                onChange={(e) => setKeepName(e.target.checked)}
              />
              Keep uploaded file name and extension
            </label>
            {!keepName ? (
              <input
                type="text"
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                placeholder="my_export.csv (extension added from source if omitted)"
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-sm outline-none focus:border-[var(--sidebar-primary)]"
              />
            ) : null}
            <p className="break-all font-mono text-[11px] text-[var(--fg-muted)]">
              Target:{' '}
              {containerMeta?.container_name ?? '…'}/
              {folderPath ? `${folderPath.replace(/\/$/, '')}/` : ''}
              {destPreview}
            </p>
          </section>

          <div className="flex justify-end border-t border-[var(--border)] pt-4">
            <Button
              variant="primary"
              disabled={!file || uploadMut.isPending}
              onClick={() => uploadMut.mutate()}
            >
              <CloudUpload className="h-4 w-4" />
              {uploadMut.isPending ? 'Uploading…' : 'Upload to Azure'}
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  )
}
