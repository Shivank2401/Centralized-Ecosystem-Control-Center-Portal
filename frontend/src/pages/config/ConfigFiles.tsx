import { useCallback, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Modal } from '@/components/ui/Modal'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'

export function ConfigFilesPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const files = useQuery({ queryKey: ['config-files'], queryFn: api.configFiles })
  const [name, setName] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)

  const fileQ = useQuery({
    queryKey: ['config-file', name],
    queryFn: () => api.configFile(name!),
    enabled: Boolean(name),
  })

  useEffect(() => {
    if (fileQ.data?.content != null) {
      setContent(fileQ.data.content)
      setDirty(false)
    }
  }, [fileQ.data?.content, name])

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  const save = useMutation({
    mutationFn: () => api.configSaveFile(name!, content),
    onSuccess: () => {
      toast.push({ kind: 'success', title: 'File saved' })
      setDirty(false)
      void qc.invalidateQueries({ queryKey: ['config-files'] })
      void qc.invalidateQueries({ queryKey: ['config-overview'] })
      void qc.invalidateQueries({ queryKey: ['config-file', name] })
    },
    onError: (e) =>
      toast.push({ kind: 'error', title: 'Save rejected', description: e instanceof Error ? e.message : undefined }),
  })

  const closeEditor = useCallback(() => {
    if (dirty && !window.confirm('Discard unsaved changes?')) return
    setName(null)
  }, [dirty])

  if (files.isLoading) return <Spinner />
  if (files.error) return <ErrorState title="Unable to list config files" onRetry={() => void files.refetch()} />

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Configuration Files"
          description="Advanced YAML editor — structured screens are preferred for normal edits"
        />
        <div className="divide-y divide-[var(--border)]">
          {(files.data ?? []).map((f) => (
            <div key={f.name} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
              <div>
                <p className="font-mono text-sm font-semibold">{f.name}</p>
                <p className="font-mono text-[11px] text-[var(--fg-muted)]">
                  {f.size_bytes} bytes · {f.modified?.slice(0, 19)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={f.valid ? 'ok' : 'danger'}>{f.valid ? 'valid' : 'invalid'}</Badge>
                <Button
                  variant="secondary"
                  onClick={() => {
                    if (dirty && !window.confirm('Discard unsaved changes?')) return
                    setName(f.name)
                  }}
                >
                  Open
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Modal
        open={Boolean(name)}
        onClose={closeEditor}
        closeOnBackdrop={!dirty}
        labelledBy="config-file-editor-title"
        title={name ?? 'Config file'}
        description={dirty ? 'Unsaved changes' : 'Saved'}
        size="full"
        headerExtra={
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                if (fileQ.data?.content != null) {
                  setContent(fileQ.data.content)
                  setDirty(false)
                }
              }}
            >
              Revert
            </Button>
            <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
              Save
            </Button>
          </div>
        }
        footer={
          <Button variant="secondary" onClick={closeEditor}>
            Close
          </Button>
        }
      >
        {fileQ.isLoading ? (
          <div className="p-5">
            <Spinner />
          </div>
        ) : (
          <textarea
            className="min-h-[min(70vh,36rem)] w-full resize-y bg-[var(--bg)] p-4 font-mono text-xs leading-relaxed outline-none"
            spellCheck={false}
            value={content}
            onChange={(e) => {
              setContent(e.target.value)
              setDirty(true)
            }}
          />
        )}
      </Modal>
    </div>
  )
}
