import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'

const titles: Record<string, { title: string; subtitle?: string }> = {
  '/': { title: 'Dashboard', subtitle: 'Operational overview of the inventory ETL ecosystem' },
  '/pipeline/run': {
    title: 'Run Pipeline',
    subtitle: 'Select client, geography, stage, and reports',
  },
  '/pipeline/active': { title: 'Active Runs', subtitle: 'Live pipeline execution' },
  '/pipeline/history': { title: 'Run History', subtitle: 'Past pipeline executions' },
  '/pipeline/sequences': { title: 'Saved Sequences', subtitle: 'Reusable run recipes' },
  '/config/clients': { title: 'Clients', subtitle: 'Client registry' },
  '/config/geographies': { title: 'Geographies', subtitle: 'Per-client geo settings' },
  '/config/reports': { title: 'Reports', subtitle: 'Report configuration' },
  '/config/stages': { title: 'Stages', subtitle: 'Pipeline stages' },
  '/config/environment': { title: 'Environment', subtitle: 'Paths and integrations (no secrets)' },
  '/reports': { title: 'All Reports', subtitle: 'Registered report modules' },
  '/reports/standard': { title: 'Standard Reports', subtitle: 'Common sanity reports' },
  '/reports/requirement': { title: 'Requirement Specific', subtitle: 'Client requirement reports' },
  '/reports/utilities': { title: 'Utilities', subtitle: 'Utility scripts' },
  '/developer/add-report': { title: 'Add Report', subtitle: 'Upload and register a new report' },
  '/developer/registry': { title: 'Report Registry', subtitle: 'Manage registered reports' },
  '/developer/validation': { title: 'Validation', subtitle: 'Validate configuration and modules' },
  '/developer/diagnostics': { title: 'System Diagnostics', subtitle: 'Health checks' },
  '/data/outputs': { title: 'Outputs', subtitle: 'Browse generated files' },
  '/data/logs': { title: 'Logs', subtitle: 'Report and run logs' },
  '/data/cogs': { title: 'COGS', subtitle: 'COGS data explorer' },
  '/data/pincode': { title: 'Pincode', subtitle: 'Pincode reference data' },
  '/settings': { title: 'Settings', subtitle: 'Portal preferences' },
}

export function AppLayout() {
  const { pathname } = useLocation()
  const meta =
    titles[pathname] ??
    (pathname.startsWith('/pipeline/runs/')
      ? { title: 'Run Detail', subtitle: 'Live progress and logs' }
      : { title: 'Inventory Ecosystem' })

  return (
    <div
      className="flex h-full min-h-0 bg-[var(--bg)]"
      style={{ backgroundImage: 'var(--surface-pattern)' }}
    >
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar title={meta.title} subtitle={meta.subtitle} />
        <main className="min-h-0 flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
