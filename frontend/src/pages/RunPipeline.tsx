import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, GripVertical } from 'lucide-react'
import { useClients, useReports, useStages } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api, ApiError } from '@/services/api'
import { cn, formatStageLabel } from '@/utils/cn'

const STEPS = ['Client', 'Geography', 'Stage', 'Reports', 'Review', 'Run'] as const

function ChoiceChip({
  selected,
  label,
  sub,
  onClick,
}: {
  selected: boolean
  label: string
  sub?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-md border px-4 py-3 text-left transition',
        selected
          ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
          : 'border-[var(--border)] bg-[var(--bg-elevated)] hover:border-[var(--accent)]/50',
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            'flex h-4 w-4 items-center justify-center rounded border',
            selected
              ? 'border-[var(--accent)] bg-[var(--accent)] text-white'
              : 'border-[var(--border)]',
          )}
        >
          {selected ? <Check className="h-3 w-3" /> : null}
        </span>
        <span className="font-mono text-sm font-semibold">{label}</span>
      </div>
      {sub ? <p className="mt-1 pl-6 text-xs text-[var(--fg-muted)]">{sub}</p> : null}
    </button>
  )
}

export function RunPipelinePage() {
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const rerun = (location.state || {}) as {
    clients?: string[]
    geos?: string[]
    reports?: string[]
  }

  const [step, setStep] = useState(0)
  const [clients, setClients] = useState<string[]>(rerun.clients ?? [])
  const [geos, setGeos] = useState<string[]>(rerun.geos ?? [])
  const [stage, setStage] = useState<string | null>(null)
  const [reports, setReports] = useState<string[]>(rerun.reports ?? [])

  const [preflight, setPreflight] = useState<{ ok: boolean; message: string } | null>(null)

  const startRun = useMutation({
    mutationFn: async () => {
      const validation = await api.validateRun({ clients, geos, reports })
      if (!validation.ok) {
        const errors = validation.checks
          .filter((c) => !c.ok && c.level === 'ERROR')
          .map((c) => c.message)
        throw new ApiError('RUN_VALIDATION_FAILED', errors.join('; ') || 'Validation failed')
      }
      setPreflight({ ok: true, message: `${validation.checks.length} checks passed` })
      return api.createRun({ clients, geos, reports })
    },
    onSuccess: (run) => {
      toast.push({
        kind: 'success',
        title: 'Run started',
        description: `Run #${run.run_id}`,
      })
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      navigate(`/pipeline/runs/${run.run_id}`)
    },
    onError: (err) => {
      const busy = err instanceof ApiError && err.code === 'PIPELINE_BUSY'
      toast.push({
        kind: 'error',
        title: busy ? 'Pipeline busy' : 'Failed to start run',
        description: err instanceof Error ? err.message : 'Unknown error',
      })
    },
  })

  const clientsQuery = useClients()
  const stagesQuery = useStages(clients.length ? clients : undefined)
  const reportsQuery = useReports({
    client: clients.length ? clients : undefined,
    stage: stage ?? undefined,
  })

  const geoOptions = useMemo(() => {
    const selected = (clientsQuery.data ?? []).filter((c) => clients.includes(c.code))
    const set = new Set<string>()
    selected.forEach((c) => c.geographies.forEach((g) => set.add(g)))
    return [...set].sort()
  }, [clientsQuery.data, clients])

  const reportMeta = useMemo(
    () => new Map((reportsQuery.data ?? []).map((r) => [r.code, r])),
    [reportsQuery.data],
  )

  const canNext =
    (step === 0 && clients.length > 0) ||
    (step === 1 && geos.length > 0) ||
    (step === 2 && Boolean(stage)) ||
    (step === 3 && reports.length > 0) ||
    step >= 4

  function toggle(list: string[], value: string, set: (v: string[]) => void) {
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value])
  }

  function moveReport(index: number, dir: -1 | 1) {
    const next = [...reports]
    const j = index + dir
    if (j < 0 || j >= next.length) return
    ;[next[index], next[j]] = [next[j], next[index]]
    setReports(next)
  }

  if (clientsQuery.isLoading) return <Spinner />
  if (clientsQuery.error) {
    return (
      <ErrorState
        title="Unable to load clients"
        message={clientsQuery.error instanceof Error ? clientsQuery.error.message : undefined}
        onRetry={() => void clientsQuery.refetch()}
      />
    )
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5">
      <ol className="flex flex-wrap gap-2">
        {STEPS.map((label, i) => (
          <li
            key={label}
            className={cn(
              'rounded-md px-3 py-1.5 font-mono text-xs',
              i === step
                ? 'bg-[var(--accent)] text-white dark:text-ink'
                : i < step
                  ? 'bg-[var(--accent-soft)] text-[var(--accent)]'
                  : 'border border-[var(--border)] bg-[var(--bg-elevated)] text-[var(--fg-muted)]',
            )}
          >
            {i + 1}. {label}
          </li>
        ))}
      </ol>

      <Panel>
        <PanelHeader
          title={STEPS[step]}
          description={
            step === 5
              ? 'Starts a background worker process. Only one run at a time.'
              : 'Preserve report order; the executor will run top to bottom.'
          }
        />
        <div className="p-5">
          {step === 0 && (
            <div className="grid gap-3 sm:grid-cols-3">
              {(clientsQuery.data ?? []).map((c) => (
                <ChoiceChip
                  key={c.code}
                  selected={clients.includes(c.code)}
                  label={c.code}
                  sub={c.name}
                  onClick={() => {
                    toggle(clients, c.code, setClients)
                    setStage(null)
                    setReports([])
                    setGeos([])
                  }}
                />
              ))}
            </div>
          )}

          {step === 1 && (
            <div className="grid gap-3 sm:grid-cols-3">
              {geoOptions.length === 0 ? (
                <EmptyState title="Select a client first" />
              ) : (
                geoOptions.map((g) => (
                  <ChoiceChip
                    key={g}
                    selected={geos.includes(g)}
                    label={g}
                    onClick={() => toggle(geos, g, setGeos)}
                  />
                ))
              )}
              <div className="sm:col-span-3">
                <Button variant="ghost" onClick={() => setGeos(geoOptions)}>
                  Select all geographies
                </Button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="grid gap-3">
              {stagesQuery.isLoading ? (
                <Spinner />
              ) : stagesQuery.error ? (
                <ErrorState
                  title="Unable to load stages"
                  message={
                    stagesQuery.error instanceof Error ? stagesQuery.error.message : undefined
                  }
                  onRetry={() => void stagesQuery.refetch()}
                />
              ) : (stagesQuery.data?.length ?? 0) === 0 ? (
                <EmptyState title="No stages for selected clients" />
              ) : (
                (stagesQuery.data ?? []).map((s) => (
                  <ChoiceChip
                    key={s.key}
                    selected={stage === s.key}
                    label={formatStageLabel(s.label)}
                    sub={s.key}
                    onClick={() => {
                      setStage(s.key)
                      setReports([])
                    }}
                  />
                ))
              )}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3">
              {reportsQuery.isLoading ? (
                <Spinner />
              ) : reportsQuery.error ? (
                <ErrorState
                  title="Unable to load reports"
                  message={
                    reportsQuery.error instanceof Error ? reportsQuery.error.message : undefined
                  }
                  onRetry={() => void reportsQuery.refetch()}
                />
              ) : (reportsQuery.data?.length ?? 0) === 0 ? (
                <EmptyState title="No reports in this stage" />
              ) : (
                <>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      onClick={() => setReports((reportsQuery.data ?? []).map((r) => r.code))}
                    >
                      Run All
                    </Button>
                    <Button variant="ghost" onClick={() => setReports([])}>
                      Clear
                    </Button>
                  </div>
                  <div className="grid gap-2">
                    {(reportsQuery.data ?? []).map((r) => (
                      <ChoiceChip
                        key={r.code}
                        selected={reports.includes(r.code)}
                        label={r.label}
                        sub={r.code}
                        onClick={() => toggle(reports, r.code, setReports)}
                      />
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4 text-sm">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-md border border-[var(--border)] p-3">
                  <p className="font-mono text-[11px] text-[var(--fg-muted)] uppercase">Clients</p>
                  <p className="mt-1 font-medium">{clients.join(', ')}</p>
                </div>
                <div className="rounded-md border border-[var(--border)] p-3">
                  <p className="font-mono text-[11px] text-[var(--fg-muted)] uppercase">
                    Geographies
                  </p>
                  <p className="mt-1 font-medium">{geos.join(', ')}</p>
                </div>
              </div>
              <div className="rounded-md border border-[var(--border)] p-3">
                <p className="font-mono text-[11px] text-[var(--fg-muted)] uppercase">Stage</p>
                <p className="mt-1 font-medium">{stage}</p>
              </div>
              <div>
                <p className="mb-2 font-mono text-[11px] text-[var(--fg-muted)] uppercase">
                  Report order
                </p>
                <ul className="space-y-2">
                  {reports.map((code, i) => (
                    <li
                      key={code}
                      className="flex items-center gap-2 rounded-md border border-[var(--border)] px-3 py-2"
                    >
                      <GripVertical className="h-4 w-4 text-[var(--fg-muted)]" />
                      <span className="font-mono text-xs text-[var(--fg-muted)]">{i + 1}.</span>
                      <span className="flex-1 font-medium">
                        {reportMeta.get(code)?.label ?? code}
                      </span>
                      <Badge>{code}</Badge>
                      <Button variant="ghost" className="!px-2" onClick={() => moveReport(i, -1)}>
                        ↑
                      </Button>
                      <Button variant="ghost" className="!px-2" onClick={() => moveReport(i, 1)}>
                        ↓
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {step === 5 && (
            <div className="space-y-4">
              <p className="text-sm text-[var(--fg-muted)]">
                Ready to execute{' '}
                <span className="font-medium text-[var(--fg)]">{reports.length}</span> report(s) for{' '}
                <span className="font-mono text-[var(--fg)]">{clients.join(',')}</span> /{' '}
                <span className="font-mono text-[var(--fg)]">{geos.join(',')}</span>.
              </p>
              <pre className="overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--bg)] p-4 font-mono text-xs">
                {JSON.stringify({ clients, geos, stage, reports }, null, 2)}
              </pre>
              {preflight ? (
                <p className="font-mono text-xs text-[var(--color-ok)]">{preflight.message}</p>
              ) : (
                <p className="text-xs text-[var(--fg-muted)]">
                  Start Run validates config/modules via the API, then spawns the pipeline worker.
                </p>
              )}
              <Button
                disabled={startRun.isPending || reports.length === 0}
                onClick={() => {
                  setPreflight(null)
                  startRun.mutate()
                }}
              >
                {startRun.isPending ? 'Validating & starting…' : 'Start Run'}
              </Button>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[var(--border)] px-5 py-4">
          <Button
            variant="secondary"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
          >
            <ChevronLeft className="h-4 w-4" />
            Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
              Continue
              <ChevronRight className="h-4 w-4" />
            </Button>
          ) : (
            <span className="text-xs text-[var(--fg-muted)]">Validate → worker → live logs</span>
          )}
        </div>
      </Panel>
    </div>
  )
}
