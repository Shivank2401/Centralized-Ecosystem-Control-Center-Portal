import { NavLink } from 'react-router-dom'
import {
  Activity,
  ChevronDown,
  Database,
  FileCode2,
  FileText,
  FolderCode,
  CloudUpload,
  FolderOutput,
  GitBranch,
  History,
  LayoutDashboard,
  MapPinned,
  Play,
  ScrollText,
  Settings,
  ShieldCheck,
  Stethoscope,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/utils/cn'

type NavItem = {
  label: string
  to: string
  icon: React.ComponentType<{ className?: string }>
}

type NavGroup = { label: string; items: NavItem[] }

const topItem: NavItem = { label: 'Dashboard', to: '/', icon: LayoutDashboard }

const groups: NavGroup[] = [
  {
    label: 'Pipeline',
    items: [
      { label: 'Run Pipeline', to: '/pipeline/run', icon: Play },
      { label: 'Active Runs', to: '/pipeline/active', icon: Activity },
      { label: 'Run History', to: '/pipeline/history', icon: History },
      { label: 'Run Sequences', to: '/pipeline/sequences', icon: GitBranch },
    ],
  },
  {
    label: 'Configuration',
    items: [
      { label: 'Overview', to: '/config', icon: LayoutDashboard },
      { label: 'Clients', to: '/config/clients', icon: Users },
      { label: 'Geographies', to: '/config/geographies', icon: MapPinned },
      { label: 'Reports', to: '/config/reports', icon: FolderCode },
      { label: 'Paths & Environment', to: '/config/environment', icon: Settings },
      { label: 'Configuration Files', to: '/config/files', icon: FileText },
      { label: 'Configuration History', to: '/config/history', icon: History },
    ],
  },
  {
    label: 'Developer',
    items: [
      { label: 'Add Report', to: '/developer/add-report', icon: FileCode2 },
      { label: 'Report Registry', to: '/developer/registry', icon: Database },
      { label: 'Validation', to: '/developer/validation', icon: ShieldCheck },
      { label: 'System Diagnostics', to: '/developer/diagnostics', icon: Stethoscope },
    ],
  },
  {
    label: 'Data',
    items: [
      { label: 'Outputs', to: '/data/outputs', icon: FolderOutput },
      { label: 'Logs', to: '/data/logs', icon: ScrollText },
      { label: 'COGS', to: '/data/cogs', icon: Database },
      { label: 'Pincode', to: '/data/pincode', icon: MapPinned },
      { label: 'Azure Upload', to: '/data/azure-upload', icon: CloudUpload },
    ],
  },
]

function linkClass({ isActive }: { isActive: boolean }) {
  return cn(
    'flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition',
    isActive
      ? 'bg-[var(--sidebar-primary)] text-[var(--sidebar-primary-foreground)] shadow-sm'
      : 'text-[var(--sidebar-foreground)]/75 hover:bg-[var(--sidebar-accent)] hover:text-[var(--sidebar-foreground)]',
  )
}

function NavGroupBlock({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mb-1 flex w-full items-center justify-between px-2.5 py-1 text-[11px] font-semibold tracking-[0.14em] text-[var(--sidebar-foreground)]/45 uppercase"
      >
        {group.label}
        <ChevronDown className={cn('h-3.5 w-3.5 transition', !open && '-rotate-90')} />
      </button>
      {open ? (
        <div className="space-y-0.5">
          {group.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/config' || item.to === '/config/reports'}
              className={linkClass}
            >
              <item.icon className="h-4 w-4 shrink-0 opacity-80" />
              <span className="truncate">{item.label}</span>
            </NavLink>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function Sidebar() {
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar)] text-[var(--sidebar-foreground)]">
      <div className="border-b border-[var(--sidebar-border)] px-4 py-4">
        <p className="font-mono text-[10px] tracking-[0.2em] text-[var(--sidebar-primary)] uppercase">
          Centralized
        </p>
        <h1 className="mt-1 text-lg leading-tight font-semibold text-[var(--sidebar-foreground)]">
          Control Center
          <span className="block text-[var(--sidebar-primary)]">Ecosystem</span>
        </h1>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <NavLink to={topItem.to} end className={linkClass}>
          <topItem.icon className="h-4 w-4 shrink-0 opacity-80" />
          {topItem.label}
        </NavLink>
        <div className="mt-4">
          {groups.map((g) => (
            <NavGroupBlock key={g.label} group={g} />
          ))}
        </div>
        <NavLink to="/settings" className={linkClass}>
          <Settings className="h-4 w-4 shrink-0 opacity-80" />
          Settings
        </NavLink>
      </nav>
      <div className="border-t border-[var(--sidebar-border)] px-4 py-3 font-mono text-[10px] text-[var(--sidebar-foreground)]/45">
        Config Center · Local-first
      </div>
    </aside>
  )
}
