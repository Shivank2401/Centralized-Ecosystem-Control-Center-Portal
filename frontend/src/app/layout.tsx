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
  '/pipeline/sequences': {
    title: 'Run Sequences',
    subtitle: 'Reusable run recipes · run_sequences.yaml',
  },
  '/config': { title: 'Configuration Overview', subtitle: 'Health and inventory of config_manager' },
  '/config/clients': { title: 'Clients', subtitle: 'client.yaml management' },
  '/config/geographies': { title: 'Geographies', subtitle: 'geography.yaml management' },
  '/config/reports': {
    title: 'Reports',
    subtitle: 'Browse folders under report_script/',
  },
  '/config/stages': { title: 'Stages', subtitle: 'report_stages management' },
  '/config/sequences': {
    title: 'Run Sequences',
    subtitle: 'Reusable run recipes · run_sequences.yaml',
  },
  '/config/environment': { title: 'Paths & Environment', subtitle: 'Local .env status (no secrets)' },
  '/config/files': { title: 'Configuration Files', subtitle: 'Advanced YAML editor' },
  '/config/history': { title: 'Configuration History', subtitle: 'Backups and diffs' },
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
      : pathname.match(/^\/config\/reports\/[^/]+$/)
        ? {
            title: decodeURIComponent(pathname.split('/').pop() || 'Package').replace(/_/g, ' '),
            subtitle: 'Scripts in this report_script package',
          }
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
