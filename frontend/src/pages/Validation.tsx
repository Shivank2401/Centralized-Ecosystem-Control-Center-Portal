import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, CircleX } from 'lucide-react'
import { useClients, useReports } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ErrorState, Spinner } from '@/components/ui/ErrorState'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import { cn } from '@/utils/cn'
import type { ValidationResult } from '@/types'

export function ValidationPage() {
  const toast = useToast()
  const clientsQ = useClients()
  const reportsQ = useReports({ enabledOnly: true })
  const [clients, setClients] = useState<string[]>([])
  const [geos, setGeos] = useState<string[]>([])
  const [reports, setReports] = useState<string[]>([])
  const [result, setResult] = useState<ValidationResult | null>(null)

  const geoOptions = useMemo(() => {
    const selected = (clientsQ.data ?? []).filter((c) => clients.includes(c.code))
    return [...new Set(selected.flatMap((c) => c.geographies))].sort()
  }, [clientsQ.data, clients])

  const validate = useMutation({
    mutationFn: () => api.validateRun({ clients, geos, reports }),
    onSuccess: (data) => {
      setResult(data)
      toast.push({
        kind: data.ok ? 'success' : 'error',
        title: data.ok ? 'Validation passed' : 'Validation found errors',
      })
    },
    onError: (err) => {
      toast.push({
        kind: 'error',
        title: 'Validation failed',
        description: err instanceof Error ? err.message : undefined,
      })
    },
  })

  const ecosystem = useMutation({
    mutationFn: () => api.validateEcosystem(),
    onSuccess: (data) => {
      setResult(data)
      toast.push({
        kind: data.ok ? 'success' : 'error',
        title: data.ok ? 'Ecosystem OK' : 'Ecosystem has errors',
      })
    },
  })

  if (clientsQ.isLoading || reportsQ.isLoading) return <Spinner />
  if (clientsQ.error || reportsQ.error) {
    return (
      <ErrorState
        title="Unable to load validation inputs"
        onRetry={() => {
          void clientsQ.refetch()
          void reportsQ.refetch()
        }}
      />
    )
  }

  function toggle(list: string[], value: string, set: (v: string[]) => void) {
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value])
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <Panel>
        <PanelHeader
          title="Pre-run Validation"
          description="Same checks the API uses before starting a pipeline run"
          action={
            <Button variant="secondary" onClick={() => ecosystem.mutate()} disabled={ecosystem.isPending}>
              Validate ecosystem
            </Button>
          }
        />
        <div className="space-y-5 p-5">
          <Section label="Clients">
            {(clientsQ.data ?? []).map((c) => (
              <Chip
                key={c.code}
                selected={clients.includes(c.code)}
                label={c.code}
                onClick={() => {
                  toggle(clients, c.code, setClients)
                  setGeos([])
                }}
              />
            ))}
          </Section>
          <Section label="Geographies">
            {geoOptions.length === 0 ? (
              <p className="text-xs text-[var(--fg-muted)]">Select clients first</p>
            ) : (
              geoOptions.map((g) => (
                <Chip
                  key={g}
                  selected={geos.includes(g)}
                  label={g}
                  onClick={() => toggle(geos, g, setGeos)}
                />
              ))
            )}
          </Section>
          <Section label="Reports">
            <div className="max-h-48 overflow-y-auto">
              <div className="flex flex-wrap gap-2">
                {(reportsQ.data ?? []).map((r) => (
                  <Chip
                    key={r.code}
                    selected={reports.includes(r.code)}
                    label={r.code}
                    onClick={() => toggle(reports, r.code, setReports)}
                  />
                ))}
              </div>
            </div>
          </Section>
          <Button
            disabled={!clients.length || !geos.length || !reports.length || validate.isPending}
            onClick={() => validate.mutate()}
          >
            Validate selection
          </Button>
        </div>
      </Panel>

      {result ? (
        <Panel>
          <PanelHeader
            title="Results"
            description={`${result.checks.length} checks`}
            action={<Badge tone={result.ok ? 'ok' : 'danger'}>{result.ok ? 'ok' : 'failed'}</Badge>}
          />
          <ul className="divide-y divide-[var(--border)]">
            {result.checks.map((c) => (
              <li key={c.name} className="flex items-start gap-3 px-5 py-2.5 text-sm">
                {c.ok ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-ok)]" />
                ) : c.level === 'WARNING' || c.level === 'WARN' ? (
                  <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-warn)]" />
                ) : (
                  <CircleX className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-danger)]" />
                )}
                <div>
                  <p className="font-mono text-xs font-semibold">{c.name}</p>
                  <p className="text-[var(--fg-muted)]">{c.message}</p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 font-mono text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">
        {label}
      </p>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  )
}

function Chip({
  selected,
  label,
  onClick,
}: {
  selected: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-md border px-2.5 py-1 font-mono text-xs transition',
        selected
          ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
          : 'border-[var(--border)] hover:border-[var(--accent)]/50',
      )}
    >
      {label}
    </button>
  )
}
