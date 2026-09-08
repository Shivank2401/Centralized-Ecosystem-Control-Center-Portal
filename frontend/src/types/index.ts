export type Client = {
  code: string
  name: string
  client_id: string
  enabled: boolean
  data_root_env: string
  cogs_path_env: string
  geographies: string[]
  layout: string
  package?: string
}

export type Geography = {
  client: string
  country_code: string
  cogs_sheet_name: string
  country_currency: string
  orders_sales_channel: string
  enabled: boolean
}

export type ReportStage = {
  key: string
  label: string
  order?: number
  clients?: string[] | null
  package_path?: string | null
}

export type Report = {
  code: string
  label: string
  stage: string
  module: string
  clients?: string[] | null
  enabled: boolean
  output_subdir?: string | null
  menu_order?: number | null
  description?: string | null
  module_file_exists: boolean
  module_importable: boolean
  package_path?: string | null
  validation_ok?: boolean
}

export type RunSequence = {
  id: string
  label: string
  clients: string[]
  geos: string[]
  reports: string[]
}

export type PipelineRunStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'SUCCESS'
  | 'FAILED'
  | 'CANCELLED'

export type PipelineRun = {
  run_id: string
  client: string[]
  geographies: string[]
  reports: string[]
  status: PipelineRunStatus
  started_at?: string | null
  completed_at?: string | null
  duration_seconds?: number | null
  current_report?: string | null
  progress: number
  completed_reports: string[]
  failed_report?: string | null
  error?: string | null
  outputs: string[]
  logs: string[]
  source: string
  pid?: number | null
  cancel_requested?: boolean
}

export type RunLogsPayload = {
  run_id: string
  offset: number
  text: string
  status: PipelineRunStatus
  progress: number
  current_report?: string | null
  completed_reports: string[]
}

export type CheckResult = {
  name: string
  ok: boolean
  level: string
  message: string
  expected?: string | null
}

export type ValidationResult = {
  ok: boolean
  checks: CheckResult[]
}

export type DiagnosticsSnapshot = {
  ok: boolean
  phase: number
  python: string
  platform: string
  project_root: string
  counts: Record<string, number>
  active_run_id?: string | null
  checks: CheckResult[]
}

export type EnvVariableStatus = {
  key: string
  set: boolean
  required: boolean
  secret: boolean
  path_like: boolean
  path_exists: boolean | null
  category: string
  value: null
}

export type EnvironmentSnapshot = {
  ok: boolean
  required_missing: string[]
  path_missing: string[]
  variables: EnvVariableStatus[]
  note: string
}

export type AstAnalysis = {
  ok: boolean
  filename: string
  module_stem: string
  syntax_ok: boolean
  has_run: boolean
  run_params: string[]
  accepts_client: boolean
  accepts_geos: boolean
  imports: string[]
  functions: string[]
  classes: string[]
  errors: string[]
  warnings: string[]
}

export type UploadAnalysis = {
  upload_id: string
  filename: string
  bytes: number
  suggested_code: string
  suggested_label: string
  analysis: AstAnalysis
  quarantine_path: string
}

export type RegistryStage = {
  key: string
  label: string
  order?: number
  clients?: string[] | null
  package_path: string
}

export type RegisterReportPayload = {
  upload_id: string
  code: string
  label: string
  stage: string
  clients?: string[] | null
  menu_order?: number | null
  enabled?: boolean
  output_subdir?: string | null
  description?: string | null
  create_stage?: { label?: string; order?: number; clients?: string[] } | null
  overwrite?: boolean
}

export type RegisterReportResult = {
  code: string
  module: string
  script_path: string
  yaml_backup: string
  enabled: boolean
  importable: boolean
  entry: Record<string, unknown>
  analysis: AstAnalysis
}

export type ImportTestResult = {
  code: string
  module: string
  file_exists: boolean
  import_ok: boolean
  error?: string | null
}

export type ExploreFile = {
  name: string
  rel: string
  ext: string
  size_bytes: number
  modified: string
  geo?: string | null
  kind: string
}

export type ReportOutputFolder = {
  client: string
  report: string
  label: string
  output_subdir: string
  path: string
  rel: string
  root: string
  exists: boolean
  file_count: number
  files: ExploreFile[]
  latest_modified?: string | null
}

export type LogReportEntry = {
  client: string
  report: string
  path: string
  rel: string
  root: string
  file_count: number
  files: ExploreFile[]
  latest?: ExploreFile | null
  latest_modified?: string | null
}

export type LogClientIndex = {
  client: string
  path: string
  exists: boolean
  reports: LogReportEntry[]
}

export type LogContent = {
  client: string
  report: string
  filename: string
  path: string
  rel: string
  root: string
  size_bytes: number
  truncated: boolean
  text: string
}

export type BrowseResult = {
  root: string
  rel: string
  path: string
  exists: boolean
  directories: { name: string; rel: string; path: string }[]
  files: ExploreFile[]
}

export type FilePreview = {
  file: ExploreFile
  root: string
  rel: string
  path: string
  preview: {
    columns?: string[]
    rows?: Record<string, unknown>[]
    text?: string
    note?: string | null
    row_count?: number
  }
}

export type ApiSuccess<T> = {
  success: true
  data: T
  message?: string
}

export type ApiErrorBody = {
  success: false
  error: {
    code: string
    message: string
    details?: unknown
  }
}

export type ApiResponse<T> = ApiSuccess<T> | ApiErrorBody

export type {
  ReportScriptFile,
  ReportScriptLink,
  ReportScriptPackage,
} from './reportScripts'
