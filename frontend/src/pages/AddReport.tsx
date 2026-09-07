import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, CircleX, Upload } from 'lucide-react'
import { useClients } from '@/hooks/useApi'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Panel, PanelHeader } from '@/components/ui/Panel'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'
import { cn, formatStageLabel } from '@/utils/cn'
import type { RegisterReportResult, UploadAnalysis } from '@/types'

const STEPS = ['Upload', 'Inspect', 'Stage', 'Metadata', 'Register'] as const

export function AddReportPage() {
  const toast = useToast()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const clientsQ = useClients()
  const stagesQ = useQuery({ queryKey: ['registry-stages'], queryFn: api.registryStages })

  const [step, setStep] = useState(0)
  const [upload, setUpload] = useState<UploadAnalysis | null>(null)
  const [stage, setStage] = useState('')
  const [newStage, setNewStage] = useState(false)
  const [stageLabel, setStageLabel] = useState('')
  const [stageOrder, setStageOrder] = useState(50)
  const [allClients, setAllClients] = useState(true)
  const [clients, setClients] = useState<string[]>([])
  const [code, setCode] = useState('')
  const [label, setLabel] = useState('')
  const [outputSubdir, setOutputSubdir] = useState('')
  const [description, setDescription] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [result, setResult] = useState<RegisterReportResult | null>(null)

  const uploadMut = useMutation({
    mutationFn: (file: File) => api.uploadReport(file),
    onSuccess: (data) => {
      setUpload(data)
      setCode(data.suggested_code)
      setLabel(data.suggested_label)
      setOutputSubdir(data.suggested_code)
      setStep(1)
      toast.push({
        kind: data.analysis.ok ? 'success' : 'error',
        title: data.analysis.ok ? 'AST validation passed' : 'AST validation failed',
      })
    },
    onError: (err) => {
      toast.push({
        kind: 'error',
        title: 'Upload rejected',
        description: err instanceof Error ? err.message : undefined,
      })
    },
  })

  const registerMut = useMutation({
    mutationFn: () =>
      api.registerReport({
        upload_id: upload!.upload_id,
        code,
        label,
        stage: newStage ? codeStageKey(stageLabel || code) : stage,
        clients: allClients ? null : clients,
        enabled,
        output_subdir: outputSubdir || null,
        description: description || null,
        create_stage: newStage
          ? { label: stageLabel || `Stage: ${code}`, order: stageOrder, clients: allClients ? undefined : clients }
          : null,
      }),
    onSuccess: (data) => {
      setResult(data)
      void qc.invalidateQueries({ queryKey: ['reports'] })
      void qc.invalidateQueries({ queryKey: ['stages'] })
      toast.push({ kind: 'success', title: 'Report registered', description: data.code })
      setStep(4)
    },
    onError: (err) => {
      toast.push({
        kind: 'error',
        title: 'Registration failed',
        description: err instanceof Error ? err.message : undefined,
      })
    },
  })

  const analysis = upload?.analysis
  const canInspectNext = Boolean(analysis?.ok)
  const canStageNext = newStage ? Boolean(stageLabel.trim()) : Boolean(stage)
  const canMetaNext = Boolean(code.trim() && label.trim())

  const packageHint = useMemo(() => {
    if (newStage) return `report_script/${codeStageKey(stageLabel || 'new_stage')}`
    const found = (stagesQ.data ?? []).find((s) => s.key === stage)
    return found?.package_path ?? ''
  }, [newStage, stage, stageLabel, stagesQ.data])

  return (
    <div className="mx-auto max-w-3xl">
      <Panel>
        <PanelHeader
          title="Add Report"
          description="Upload → AST validate → stage → register into report.yaml (no ETL rewrite)"
        />
        <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-3">
          {STEPS.map((s, i) => (
            <Badge key={s} tone={i === step ? 'accent' : i < step ? 'ok' : 'neutral'}>
              {i + 1}. {s}
            </Badge>
          ))}
        </div>

        <div className="space-y-4 p-5">
          {step === 0 && (
            <label
              className={cn(
                'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)] px-6 py-16 transition hover:border-[var(--accent)]',
                uploadMut.isPending && 'opacity-60',
              )}
            >
              <Upload className="h-8 w-8 text-[var(--accent)]" />
              <p className="text-sm font-medium">Drop a .py file or browse</p>
              <p className="text-xs text-[var(--fg-muted)]">
                Static AST validation only — code is not executed until you register and run a pipeline.
              </p>
              <input
                type="file"
                accept=".py,text/x-python"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) uploadMut.mutate(f)
                }}
              />
            </label>
          )}

          {step === 1 && analysis && upload && (
            <div className="space-y-3 text-sm">
              <Row k="File" v={upload.filename} />
              <Row k="Module" v={analysis.module_stem} />
              <Row k="Quarantine" v={upload.quarantine_path} />
              <div className="flex flex-wrap gap-2">
                <Badge tone={analysis.syntax_ok ? 'ok' : 'danger'}>syntax</Badge>
                <Badge tone={analysis.has_run ? 'ok' : 'danger'}>run()</Badge>
                <Badge tone={analysis.accepts_client ? 'ok' : 'danger'}>client</Badge>
                <Badge tone={analysis.accepts_geos ? 'ok' : 'warn'}>geos</Badge>
              </div>
              <p className="font-mono text-xs text-[var(--fg-muted)]">
                params: {analysis.run_params.join(', ') || '—'}
              </p>
              <p className="font-mono text-xs text-[var(--fg-muted)]">
                imports: {analysis.imports.join(', ') || '—'}
              </p>
              {analysis.errors.map((e) => (
                <p key={e} className="flex gap-2 text-[var(--color-danger)]">
                  <CircleX className="h-4 w-4 shrink-0" /> {e}
                </p>
              ))}
              {analysis.warnings.map((w) => (
                <p key={w} className="flex gap-2 text-[var(--color-warn)]">
                  <CircleAlert className="h-4 w-4 shrink-0" /> {w}
                </p>
              ))}
              {analysis.ok ? (
                <p className="flex gap-2 text-[var(--color-ok)]">
                  <CheckCircle2 className="h-4 w-4" /> Ready for stage selection
                </p>
              ) : null}
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <div className="flex gap-2">
                <Button variant={!newStage ? 'primary' : 'secondary'} onClick={() => setNewStage(false)}>
                  Existing stage
                </Button>
                <Button variant={newStage ? 'primary' : 'secondary'} onClick={() => setNewStage(true)}>
                  Create new stage
                </Button>
              </div>
              {!newStage ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {(stagesQ.data ?? []).map((s) => (
                    <button
                      key={s.key}
                      type="button"
                      onClick={() => setStage(s.key)}
                      className={cn(
                        'rounded-md border px-3 py-2 text-left text-sm',
                        stage === s.key
                          ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
                          : 'border-[var(--border)]',
                      )}
                    >
                      <p className="font-medium">{formatStageLabel(s.label)}</p>
                      <p className="font-mono text-[10px] text-[var(--fg-muted)]">{s.package_path}</p>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Stage label">
                    <input
                      className="input"
                      value={stageLabel}
                      onChange={(e) => setStageLabel(e.target.value)}
                      placeholder="Stage: custom analytics"
                    />
                  </Field>
                  <Field label="Menu order">
                    <input
                      className="input"
                      type="number"
                      value={stageOrder}
                      onChange={(e) => setStageOrder(Number(e.target.value))}
                    />
                  </Field>
                </div>
              )}
              {packageHint ? (
                <p className="font-mono text-xs text-[var(--fg-muted)]">Package: {packageHint}</p>
              ) : null}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Report code">
                  <input className="input font-mono" value={code} onChange={(e) => setCode(e.target.value)} />
                </Field>
                <Field label="Label">
                  <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} />
                </Field>
                <Field label="Output subdir (optional)">
                  <input
                    className="input font-mono"
                    value={outputSubdir}
                    onChange={(e) => setOutputSubdir(e.target.value)}
                  />
                </Field>
                <Field label="Enabled">
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
                    Show in menus
                  </label>
                </Field>
              </div>
              <Field label="Description">
                <textarea
                  className="input min-h-[72px]"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Field>
              <div>
                <p className="mb-2 font-mono text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">
                  Client scope
                </p>
                <div className="mb-2 flex gap-2">
                  <Button variant={allClients ? 'primary' : 'secondary'} onClick={() => setAllClients(true)}>
                    All clients
                  </Button>
                  <Button variant={!allClients ? 'primary' : 'secondary'} onClick={() => setAllClients(false)}>
                    Specific
                  </Button>
                </div>
                {!allClients ? (
                  <div className="flex flex-wrap gap-2">
                    {(clientsQ.data ?? []).map((c) => (
                      <button
                        key={c.code}
                        type="button"
                        className={cn(
                          'rounded-md border px-2.5 py-1 font-mono text-xs',
                          clients.includes(c.code)
                            ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
                            : 'border-[var(--border)]',
                        )}
                        onClick={() =>
                          setClients((prev) =>
                            prev.includes(c.code) ? prev.filter((x) => x !== c.code) : [...prev, c.code],
                          )
                        }
                      >
                        {c.code}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4 text-sm">
              {!result ? (
                <>
                  <pre className="overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--bg)] p-4 font-mono text-xs">
                    {JSON.stringify(
                      {
                        upload_id: upload?.upload_id,
                        code,
                        label,
                        stage: newStage ? codeStageKey(stageLabel || code) : stage,
                        clients: allClients ? null : clients,
                        output_subdir: outputSubdir || null,
                        enabled,
                      },
                      null,
                      2,
                    )}
                  </pre>
                  <Button disabled={registerMut.isPending} onClick={() => registerMut.mutate()}>
                    {registerMut.isPending ? 'Registering…' : 'Confirm registration'}
                  </Button>
                </>
              ) : (
                <div className="space-y-3">
                  {[
                    'Script copied into report_script',
                    'report.yaml updated (backup saved)',
                    'Import test passed',
                    'Report ready in UI / CLI',
                  ].map((t) => (
                    <p key={t} className="flex gap-2 text-[var(--color-ok)]">
                      <CheckCircle2 className="h-4 w-4" /> {t}
                    </p>
                  ))}
                  <p className="font-mono text-xs text-[var(--fg-muted)]">
                    {result.module} · backup {result.yaml_backup}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      onClick={() =>
                        navigate('/pipeline/run', {
                          state: { reports: [result.code], clients: allClients ? undefined : clients },
                        })
                      }
                    >
                      Run in wizard
                    </Button>
                    <Link to="/developer/registry">
                      <Button variant="secondary">Report Registry</Button>
                    </Link>
                    <Link to="/reports">
                      <Button variant="ghost">All Reports</Button>
                    </Link>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-between border-t border-[var(--border)] px-5 py-4">
          <Button
            variant="secondary"
            disabled={step === 0 || (step === 4 && Boolean(result))}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
          >
            Back
          </Button>
          {step < 4 ? (
            <Button
              disabled={
                (step === 1 && !canInspectNext) ||
                (step === 2 && !canStageNext) ||
                (step === 3 && !canMetaNext) ||
                step === 0
              }
              onClick={() => setStep((s) => s + 1)}
            >
              Continue
            </Button>
          ) : null}
        </div>
      </Panel>
      <style>{`
        .input {
          width: 100%;
          border-radius: 0.375rem;
          border: 1px solid var(--border);
          background: var(--bg);
          padding: 0.5rem 0.75rem;
          font-size: 0.875rem;
        }
      `}</style>
    </div>
  )
}

function codeStageKey(label: string) {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^stage_/, '')
    .replace(/^_+|_+$/g, '') || 'custom'
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <p className="font-mono text-[11px] text-[var(--fg-muted)] uppercase">{k}</p>
      <p className="font-mono text-xs">{v}</p>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="font-mono text-[11px] tracking-wider text-[var(--fg-muted)] uppercase">{label}</span>
      {children}
    </label>
  )
}
