import type { Report, ReportStage } from '@/types'

export const UNASSIGNED_STAGE_KEY = '__unassigned__'
export const EXPANDED_STAGES_STORAGE_KEY = 'iep-config-reports-expanded'

export function normalizeStageKey(stage: string | null | undefined): string {
  const raw = String(stage ?? '')
    .trim()
    .toLowerCase()
  if (!raw) return UNASSIGNED_STAGE_KEY
  const key = raw.replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || UNASSIGNED_STAGE_KEY
  // Keep in sync with pipeline_engine.registry.STAGE_ALIASES
  const aliases: Record<string, string> = {
    amazon_reportss: 'common',
    amazon_reports: 'common',
    supply_chain: 'helper_files_nd_saving',
  }
  return aliases[key] ?? key
}

export function formatStageDisplayName(labelOrKey: string): string {
  return labelOrKey.replace(/^Stage:\s*/i, '').trim() || labelOrKey
}

export type ReportAttention = 'ok' | 'paused' | 'attention'

export function reportAttention(r: Report): ReportAttention {
  if (!r.enabled) return 'paused'
  if (!r.module_file_exists || !r.module_importable) return 'attention'
  return 'ok'
}

export function sortReportsInStage(reports: Report[]): Report[] {
  return [...reports].sort((a, b) => {
    const aAtt = reportAttention(a)
    const bAtt = reportAttention(b)
    const attRank = { attention: 0, ok: 1, paused: 2 }
    if (attRank[aAtt] !== attRank[bAtt]) return attRank[aAtt] - attRank[bAtt]
    const ao = a.menu_order ?? 999
    const bo = b.menu_order ?? 999
    if (ao !== bo) return ao - bo
    return a.label.localeCompare(b.label)
  })
}

export type StageBundleModel = {
  key: string
  label: string
  order: number
  reports: Report[]
  enabledCount: number
  pausedCount: number
  attentionCount: number
  configured: boolean
}

export function buildStageBundles(
  reports: Report[],
  stages: ReportStage[],
  opts: { showEmpty: boolean },
): StageBundleModel[] {
  const byKey = new Map<string, StageBundleModel>()

  for (const s of stages) {
    const key = normalizeStageKey(s.key)
    byKey.set(key, {
      key,
      label: formatStageDisplayName(s.label || s.key),
      order: s.order ?? 999,
      reports: [],
      enabledCount: 0,
      pausedCount: 0,
      attentionCount: 0,
      configured: true,
    })
  }

  for (const r of reports) {
    const key = normalizeStageKey(r.stage)
    let bundle = byKey.get(key)
    if (!bundle) {
      bundle = {
        key,
        label: key === UNASSIGNED_STAGE_KEY ? 'Unassigned' : formatStageDisplayName(r.stage || key),
        order: 10_000,
        reports: [],
        enabledCount: 0,
        pausedCount: 0,
        attentionCount: 0,
        configured: false,
      }
      byKey.set(key, bundle)
    }
    bundle.reports.push(r)
  }

  for (const bundle of byKey.values()) {
    bundle.reports = sortReportsInStage(bundle.reports)
    bundle.enabledCount = bundle.reports.filter((r) => r.enabled).length
    bundle.pausedCount = bundle.reports.filter((r) => !r.enabled).length
    bundle.attentionCount = bundle.reports.filter((r) => reportAttention(r) === 'attention').length
  }

  return [...byKey.values()]
    .filter((b) => (opts.showEmpty ? true : b.reports.length > 0))
    .sort((a, b) => {
      if (a.key === UNASSIGNED_STAGE_KEY) return 1
      if (b.key === UNASSIGNED_STAGE_KEY) return -1
      if (a.order !== b.order) return a.order - b.order
      return a.label.localeCompare(b.label)
    })
}

export function readExpandedStages(): string[] | null {
  try {
    const raw = localStorage.getItem(EXPANDED_STAGES_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? parsed.map(String) : null
  } catch {
    return null
  }
}

export function writeExpandedStages(keys: string[]) {
  try {
    localStorage.setItem(EXPANDED_STAGES_STORAGE_KEY, JSON.stringify(keys))
  } catch {
    /* ignore quota / private mode */
  }
}
