export type ReportScriptLink = {
  code: string
  label: string
  enabled: boolean
  clients?: string[] | null
  stage?: string
}

export type ReportScriptFile = {
  file: string
  stem: string
  module: string
  has_run: boolean
  registered: boolean
  can_run: boolean
  reports: ReportScriptLink[]
  report_code?: string | null
  label: string
  clients?: string[] | null
  enabled?: boolean | null
  size_bytes: number
}

export type ReportScriptPackage = {
  name: string
  path: string
  stage_key?: string | null
  stage_label?: string | null
  script_count: number
  registered_count: number
  runnable_count: number
  scripts: ReportScriptFile[]
}
