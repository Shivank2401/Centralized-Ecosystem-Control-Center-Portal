import { NavLink } from 'react-router-dom'
import {
  Activity,
  Boxes,
  ChevronDown,
  Database,
  FileCode2,
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
  Wrench,
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
      { label: 'Saved Sequences', to: '/pipeline/sequences', icon: GitBranch },
    ],
  },
  {
    label: 'Configuration',
    items: [
      { label: 'Clients', to: '/config/clients', icon: Users },
      { label: 'Geographies', to: '/config/geographies', icon: MapPinned },
      { label: 'Reports', to: '/config/reports', icon: Boxes },
      { label: 'Stages', to: '/config/stages', icon: LayoutDashboard },
      { label: 'Environment', to: '/config/environment', icon: Settings },
    ],
  },
  {
    label: 'Reports',
    items: [
      { label: 'All Reports', to: '/reports', icon: Boxes },
      { label: 'Standard', to: '/reports/standard', icon: Boxes },
      { label: 'Requirement Specific', to: '/reports/requirement', icon: Boxes },
      { label: 'Utilities', to: '/reports/utilities', icon: Wrench },
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
    ],
  },
]

function linkClass({ isActive }: { isActive: boolean }) {
  return cn(
    'flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition',
    isActive
      ? 'bg-teal-500/15 text-teal-300'
      : 'text-[var(--color-sidebar-text)] hover:bg-[var(--color-sidebar-hover)] hover:text-white',
  )
}

function NavGroupBlock({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mb-1 flex w-full items-center justify-between px-2.5 py-1 text-[11px] font-semibold tracking-[0.14em] text-slate-500 uppercase"
      >
        {group.label}
        <ChevronDown className={cn('h-3.5 w-3.5 transition', !open && '-rotate-90')} />
      </button>
      {open ? (
        <div className="space-y-0.5">
          {group.items.map((item) => (
            <NavLink key={item.to} to={item.to} className={linkClass}>
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
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-slate-800 bg-[var(--color-sidebar)] text-slate-200">
      <div className="border-b border-slate-800 px-4 py-4">
        <p className="font-mono text-[10px] tracking-[0.2em] text-teal-400/80 uppercase">
        Centralized
        </p>
        <h1 className="mt-1 text-lg leading-tight font-semibold text-white">
           Control Center
          <span className="block text-teal-300">Ecosystem</span>
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
      <div className="border-t border-slate-800 px-4 py-3 font-mono text-[10px] text-slate-500">
        Phase 6 · Data explorers
      </div>
    </aside>
  )
}
