import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import {
  formatStageDisplayName,
  normalizeStageKey,
  UNASSIGNED_STAGE_KEY,
} from '@/components/config/reports'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api, ApiError } from '@/services/api'
import type { Report, RunSequence } from '@/types'

type SeqForm = RunSequence & { enabled?: boolean }

export function ConfigSequencesPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [edit, setEdit] = useState<(SeqForm & { isNew?: boolean }) | null>(null)

  const sequences = useQuery({ queryKey: ['config-sequences'], queryFn: api.configSequences })
  const clients = useQuery({ queryKey: ['config-clients'], queryFn: api.configClients })
  const reports = useQuery({ queryKey: ['config-reports'], queryFn: api.configReports })
  const stages = useQuery({ queryKey: ['config-stages'], queryFn: api.configStages })

  const save = useMutation({
    mutationFn: async () => {
      if (!edit) throw new Error('none')
      if (!edit.clients.length) throw new Error('At least one client is required')
      if (!edit.geos.length) throw new Error('At least one geography is required — select from the Geographies list')
      if (!edit.reports.length) throw new Error('At least one report is required')
      const body = {
        label: edit.label,
        clients: edit.clients,
        geos: edit.geos,
        reports: edit.reports,
        enabled: edit.enabled ?? true,
      }
      const v = await api.configValidateSequence(body)
      if (!v.ok) throw new Error(v.errors.join('\n'))
      return api.configSaveSequence(edit.id, body, Boolean(edit.isNew))
    },
    onSuccess: () => {
      toast.push({ kind: 'success', title: 'Sequence saved' })
      setEdit(null)
      void qc.invalidateQueries({ queryKey: ['config-sequences'] })
      void qc.invalidateQueries({ queryKey: ['sequences'] })
    },
    onError: (e) =>
      toast.push({ kind: 'error', title: 'Cannot save sequence', description: e instanceof Error ? e.message : undefined }),
  })

  const runSeq = useMutation({
    mutationFn: (id: string) => api.runSequence(id),
    onSuccess: (run) => {
      toast.push({ kind: 'success', title: 'Sequence started', description: run.run_id })
      navigate(`/pipeline/runs/${run.run_id}`)
    },
    onError: (err) => {
      const busy = err instanceof ApiError && err.code === 'PIPELINE_BUSY'
      toast.push({
        kind: 'error',
        title: busy ? 'Pipeline busy' : 'Failed to start',
        description: err instanceof Error ? err.message : undefined,
      })
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.configDeleteSequence(id),
    onSuccess: () => {
      toast.push({ kind: 'success', title: 'Sequence deleted' })
      void qc.invalidateQueries({ queryKey: ['config-sequences'] })
    },
  })

  const dup = useMutation({
    mutationFn: (id: string) => api.configDuplicateSequence(id),
    onSuccess: () => {
      toast.push({ kind: 'success', title: 'Sequence duplicated' })
      void qc.invalidateQueries({ queryKey: ['config-sequences'] })
    },
  })

  const filtered = useMemo(() => {
    return (sequences.data ?? []).filter((s) => {
      if (!q) return true
      const t = q.toLowerCase()
      return s.id.includes(t) || s.label.toLowerCase().includes(t) || s.clients.join(',').toLowerCase().includes(t)
    })
  }, [sequences.data, q])

  const geoOptions = useMemo(() => {
    if (!edit) return []
    const selected = (clients.data ?? []).filter((c) => edit.clients.includes(c.code))
    return [...new Set(selected.flatMap((c) => c.geographies))].sort()
  }, [edit, clients.data])

  const selectableReports = useMemo(() => {
    const all = (reports.data ?? []).filter((r) => r.enabled)
    if (!edit?.clients.length) return all
    const selected = new Set(edit.clients.map((c) => c.toUpperCase()))
    return all.filter((r) => {
      if (!r.clients?.length) return true
      return r.clients.some((c) => selected.has(c.toUpperCase()))
    })
  }, [reports.data, edit?.clients])

  const reportsByStage = useMemo(() => {
    const stageMeta = new Map(
      (stages.data ?? []).map((s) => [
        normalizeStageKey(s.key),
        { label: formatStageDisplayName(s.label || s.key), order: s.order ?? 999 },
      ]),
    )
    const groups = new Map<string, { key: string; label: string; order: number; reports: Report[] }>()
    for (const r of selectableReports) {
      const key = normalizeStageKey(r.stage)
      let g = groups.get(key)
      if (!g) {
        const meta = stageMeta.get(key)
        g = {
          key,
          label:
            meta?.label ??
            (key === UNASSIGNED_STAGE_KEY ? 'Unassigned' : formatStageDisplayName(r.stage || key)),
          order: meta?.order ?? 10_000,
          reports: [],
        }
        groups.set(key, g)
      }
      g.reports.push(r)
    }
    for (const g of groups.values()) {
      g.reports.sort(
        (a, b) => (a.menu_order ?? 999) - (b.menu_order ?? 999) || a.code.localeCompare(b.code),
      )
    }
    return [...groups.values()].sort((a, b) => a.order - b.order || a.label.localeCompare(b.label))
  }, [selectableReports, stages.data])

  const geosForClients = (clientCodes: string[]) => {
    const selected = (clients.data ?? []).filter((c) => clientCodes.includes(c.code))
    return [...new Set(selected.flatMap((c) => c.geographies))].sort()
  }

  if (sequences.isLoading) return <Spinner />
  if (sequences.error) return <ErrorState title="Unable to load sequences" onRetry={() => void sequences.refetch()} />

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Run Sequences"
          description="Persists to config_manager/run_sequences.yaml"
          action={
            <Button
              onClick={() =>
                setEdit({
                  id: 'new_sequence',
                  label: 'New sequence',
                  clients: [],
                  geos: [],
                  reports: [],
                  enabled: true,
                  isNew: true,
                })
              }
            >
              Create sequence
            </Button>
          }
        />
        <div className="border-b border-[var(--border)] px-5 py-3">
          <input
            className="rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-sm"
            placeholder="Search…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {filtered.length === 0 ? (
          <EmptyState title="No sequences" />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {filtered.map((s) => (
              <div key={s.id} className="px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold">{s.label}</h3>
                      <Badge tone="accent">{s.id}</Badge>
                    </div>
                    <p className="mt-1 font-mono text-xs text-[var(--fg-muted)]">
                      {s.clients.join(', ')} · {s.geos.join(', ')} · {s.reports.length} reports
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={() => runSeq.mutate(s.id)} disabled={runSeq.isPending}>
                      <Play className="h-4 w-4" /> Run
                    </Button>
                    <Button variant="secondary" onClick={() => setEdit({ ...s })}>
                      Edit
                    </Button>
                    <Button variant="ghost" onClick={() => dup.mutate(s.id)}>
                      Duplicate
                    </Button>
                    <Button variant="danger" onClick={() => remove.mutate(s.id)}>
                      Delete
                    </Button>
                  </div>
                </div>
                <ol className="mt-2 space-y-0.5 font-mono text-xs text-[var(--fg-muted)]">
                  {s.reports.map((r, i) => (
                    <li key={`${s.id}-${r}-${i}`}>
                      {i + 1}. {r}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {edit ? (
        <Panel>
          <PanelHeader title={edit.isNew ? 'Create sequence' : `Edit ${edit.id}`} />
          <div className="space-y-4 p-5">
            <div className="grid gap-3 sm:grid-cols-2">
              {edit.isNew ? (
                <label className="space-y-1 text-sm">
                  <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">ID</span>
                  <input
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono"
                    value={edit.id}
                    onChange={(e) =>
                      setEdit({ ...edit, id: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })
                    }
                  />
                </label>
              ) : null}
              <label className="space-y-1 text-sm">
                <span className="font-mono text-[11px] uppercase text-[var(--fg-muted)]">Label</span>
                <input
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
                  value={edit.label}
                  onChange={(e) => setEdit({ ...edit, label: e.target.value })}
                />
              </label>
            </div>
            <ChipGroup
              label="Clients"
              options={(clients.data ?? []).map((c) => c.code)}
              selected={edit.clients}
              onChange={(clientsSel) => {
                const available = geosForClients(clientsSel)
                const kept = edit.geos.filter((g) => available.includes(g))
                setEdit({
                  ...edit,
                  clients: clientsSel,
                  geos: kept.length ? kept : available,
                })
              }}
            />
            <div>
              <ChipGroup
                label="Geographies"
                options={geoOptions}
                selected={edit.geos}
                onChange={(geos) => setEdit({ ...edit, geos })}
              />
              {!edit.clients.length ? (
                <p className="mt-1.5 text-xs text-[var(--fg-muted)]">Select a client to load geographies.</p>
              ) : !edit.geos.length ? (
                <p className="mt-1.5 text-xs text-[var(--color-warn)]">
                  Select at least one geography (required to save).
                </p>
              ) : null}
            </div>
            <div>
              <p className="mb-2 font-mono text-[11px] uppercase text-[var(--fg-muted)]">Reports (order)</p>
              {reportsByStage.length === 0 ? (
                <p className="text-sm text-[var(--fg-muted)]">
                  No enabled reports match the selected clients.
                </p>
              ) : (
                <div className="mb-3 max-h-80 space-y-3 overflow-y-auto rounded-lg border border-[var(--border)] p-3">
                  {reportsByStage.map((group) => (
                    <div key={group.key}>
                      <div className="mb-1.5 flex items-baseline justify-between gap-2">
                        <p className="text-xs font-semibold tracking-wide text-[var(--fg)] uppercase">
                          {group.label}
                        </p>
                        <span className="text-[10px] text-[var(--fg-muted)]">
                          {group.reports.length} available
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {group.reports.map((r) => (
                          <button
                            key={r.code}
                            type="button"
                            title={r.label}
                            className={`rounded-md border px-2 py-1 font-mono text-xs ${
                              edit.reports.includes(r.code)
                                ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
                                : 'border-[var(--border)]'
                            }`}
                            onClick={() =>
                              setEdit({
                                ...edit,
                                reports: edit.reports.includes(r.code)
                                  ? edit.reports.filter((x) => x !== r.code)
                                  : [...edit.reports, r.code],
                              })
                            }
                          >
                            {r.code}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {!edit.reports.length ? (
                <p className="mb-2 text-xs text-[var(--color-warn)]">Select at least one report (required to save).</p>
              ) : null}
              <ul className="space-y-1">
                {edit.reports.map((code, i) => (
                  <li
                    key={`${code}-${i}`}
                    className="flex items-center gap-2 rounded-md border border-[var(--border)] px-3 py-1.5 font-mono text-xs"
                  >
                    <span className="text-[var(--fg-muted)]">{i + 1}.</span>
                    <span className="flex-1">{code}</span>
                    <Button
                      variant="ghost"
                      className="!px-2"
                      onClick={() => {
                        if (i === 0) return
                        const next = [...edit.reports]
                        ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
                        setEdit({ ...edit, reports: next })
                      }}
                    >
                      ↑
                    </Button>
                    <Button
                      variant="ghost"
                      className="!px-2"
                      onClick={() => {
                        if (i >= edit.reports.length - 1) return
                        const next = [...edit.reports]
                        ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
                        setEdit({ ...edit, reports: next })
                      }}
                    >
                      ↓
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <div className="flex gap-2 border-t border-[var(--border)] px-5 py-3">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              Save
            </Button>
            <Button variant="ghost" onClick={() => setEdit(null)}>
              Cancel
            </Button>
          </div>
        </Panel>
      ) : null}
    </div>
  )
}

function ChipGroup({
  label,
  options,
  selected,
  onChange,
}: {
  label: string
  options: string[]
  selected: string[]
  onChange: (v: string[]) => void
}) {
  return (
    <div>
      <p className="mb-2 font-mono text-[11px] uppercase text-[var(--fg-muted)]">{label}</p>
      <div className="flex flex-wrap gap-2">
        {options.length === 0 ? (
          <span className="text-xs text-[var(--fg-muted)]">No options</span>
        ) : (
          options.map((o) => (
            <button
              key={o}
              type="button"
              className={`rounded-md border px-2.5 py-1 font-mono text-xs ${
                selected.includes(o) ? 'border-[var(--accent)] bg-[var(--accent-soft)]' : 'border-[var(--border)]'
              }`}
              onClick={() =>
                onChange(selected.includes(o) ? selected.filter((x) => x !== o) : [...selected, o])
              }
            >
              {o}
            </button>
          ))
        )}
      </div>
    </div>
  )
}
