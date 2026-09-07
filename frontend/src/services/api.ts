import type {
  ApiResponse,
  Client,
  DiagnosticsSnapshot,
  EnvironmentSnapshot,
  Geography,
  ImportTestResult,
  LogClientIndex,
  LogContent,
  PipelineRun,
  RegisterReportPayload,
  RegisterReportResult,
  RegistryStage,
  Report,
  ReportOutputFolder,
  ReportStage,
  RunLogsPayload,
  RunSequence,
  UploadAnalysis,
  ValidationResult,
} from '@/types'

export class ApiError extends Error {
  code: string
  status: number

  constructor(code: string, message: string, status = 400) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  let body: ApiResponse<T> | null = null
  try {
    body = (await res.json()) as ApiResponse<T>
  } catch {
    throw new ApiError('INVALID_JSON', 'Server returned a non-JSON response', res.status)
  }

  if (!body.success) {
    throw new ApiError(body.error.code, body.error.message, res.status)
  }

  return body.data
}

export const api = {
  health: () => request<{ status: string; service: string; phase: number }>('/api/health'),
  clients: () => request<Client[]>('/api/clients'),
  client: (code: string) => request<Client>(`/api/clients/${code}`),
  geographies: (client: string) =>
    request<Geography[]>(`/api/geographies/${encodeURIComponent(client)}`),
  stages: (clients?: string[]) => {
    const q = clients?.length ? `?client=${clients.join(',')}` : ''
    return request<ReportStage[]>(`/api/stages${q}`)
  },
  reports: (opts?: { client?: string[]; stage?: string; enabledOnly?: boolean }) => {
    const params = new URLSearchParams()
    if (opts?.client?.length) params.set('client', opts.client.join(','))
    if (opts?.stage) params.set('stage', opts.stage)
    if (opts?.enabledOnly === false) params.set('enabled_only', 'false')
    const q = params.toString() ? `?${params}` : ''
    return request<Report[]>(`/api/reports${q}`)
  },
  sequences: () => request<RunSequence[]>('/api/sequences'),
  refreshConfig: () =>
    request<{ refreshed: boolean }>('/api/config/refresh', { method: 'POST' }),

  createRun: (body: { clients: string[]; geos: string[]; reports: string[] }) =>
    request<PipelineRun>('/api/runs', { method: 'POST', body: JSON.stringify(body) }),
  runs: (opts?: { limit?: number; status?: string; client?: string }) => {
    const params = new URLSearchParams()
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.status) params.set('status', opts.status)
    if (opts?.client) params.set('client', opts.client)
    const q = params.toString() ? `?${params}` : ''
    return request<PipelineRun[]>(`/api/runs${q}`)
  },
  activeRun: () => request<PipelineRun | null>('/api/runs/active'),
  run: (runId: string) => request<PipelineRun>(`/api/runs/${encodeURIComponent(runId)}`),
  cancelRun: (runId: string) =>
    request<PipelineRun>(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }),
  runLogs: (runId: string, offset = 0) =>
    request<RunLogsPayload>(
      `/api/runs/${encodeURIComponent(runId)}/logs?offset=${offset}`,
    ),

  diagnostics: () => request<DiagnosticsSnapshot>('/api/diagnostics'),
  environment: () => request<EnvironmentSnapshot>('/api/environment'),
  validateRun: (body: { clients: string[]; geos: string[]; reports: string[] }) =>
    request<ValidationResult>('/api/validate', { method: 'POST', body: JSON.stringify(body) }),
  validateEcosystem: (client?: string) => {
    const q = client ? `?client=${encodeURIComponent(client)}` : ''
    return request<ValidationResult>(`/api/validate/ecosystem${q}`)
  },
  runSequence: (sequenceId: string) =>
    request<PipelineRun>(`/api/sequences/${encodeURIComponent(sequenceId)}/run`, {
      method: 'POST',
    }),

  registryStages: () => request<RegistryStage[]>('/api/registry/stages'),
  uploadReport: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/registry/upload', { method: 'POST', body: form })
    const body = (await res.json()) as ApiResponse<UploadAnalysis>
    if (!body.success) {
      throw new ApiError(body.error.code, body.error.message, res.status)
    }
    return body.data
  },
  registerReport: (body: RegisterReportPayload) =>
    request<RegisterReportResult>('/api/registry/register', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  setReportEnabled: (code: string, enabled: boolean) =>
    request<{ code: string; enabled: boolean }>(
      `/api/reports/${encodeURIComponent(code)}/enabled`,
      { method: 'POST', body: JSON.stringify({ enabled }) },
    ),
  testReportImport: (code: string) =>
    request<ImportTestResult>(`/api/reports/${encodeURIComponent(code)}/test-import`, {
      method: 'POST',
    }),

  exploreOutputs: (opts?: { client?: string; report?: string }) => {
    const params = new URLSearchParams()
    if (opts?.client) params.set('client', opts.client)
    if (opts?.report) params.set('report', opts.report)
    const q = params.toString() ? `?${params}` : ''
    return request<ReportOutputFolder[]>(`/api/explore/outputs${q}`)
  },
  exploreLogs: (client?: string) => {
    const q = client ? `?client=${encodeURIComponent(client)}` : ''
    return request<LogClientIndex[]>(`/api/explore/logs${q}`)
  },
  exploreLogContent: (client: string, report: string, file = 'latest.log') => {
    const params = new URLSearchParams({ client, report, file })
    return request<LogContent>(`/api/explore/logs/content?${params}`)
  },
  exploreBrowse: (root: string, rel = '') => {
    const params = new URLSearchParams({ root, rel })
    return request<import('@/types').BrowseResult>(`/api/explore/browse?${params}`)
  },
  explorePreview: (root: string, rel: string, rows = 20) => {
    const params = new URLSearchParams({ root, rel, rows: String(rows) })
    return request<import('@/types').FilePreview>(`/api/explore/file/preview?${params}`)
  },
  exploreDownloadUrl: (root: string, rel: string) =>
    `/api/explore/file/download?root=${encodeURIComponent(root)}&rel=${encodeURIComponent(rel)}`,
  exploreCogs: (client?: string) => {
    const q = client ? `?client=${encodeURIComponent(client)}` : ''
    return request<unknown>(`/api/explore/cogs${q}`)
  },
  explorePincode: () => request<import('@/types').BrowseResult>('/api/explore/pincode'),
}
