import { Moon, RefreshCw, Sun, Wifi, WifiOff } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useTheme } from '@/app/theme'
import { useHealth } from '@/hooks/useApi'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'
import { api } from '@/services/api'

export function TopBar({ title, subtitle }: { title: string; subtitle?: string }) {
  const { theme, toggle } = useTheme()
  const health = useHealth()
  const queryClient = useQueryClient()
  const toast = useToast()
  const online = health.isSuccess && health.data?.status === 'ok'

  return (
    <header className="flex items-center justify-between gap-4 border-b border-[var(--border)] bg-[var(--bg-elevated)]/80 px-6 py-3 backdrop-blur">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="text-sm text-[var(--fg-muted)]">{subtitle}</p> : null}
      </div>
      <div className="flex items-center gap-2">
        <div className="hidden items-center gap-2 rounded-md border border-[var(--border)] px-2.5 py-1.5 font-mono text-xs sm:flex">
          {online ? (
            <Wifi className="h-3.5 w-3.5 text-[var(--color-ok)]" />
          ) : (
            <WifiOff className="h-3.5 w-3.5 text-[var(--color-danger)]" />
          )}
          <span className="text-[var(--fg-muted)]">
            {online ? 'API · online' : health.isLoading ? 'API · …' : 'API · offline'}
          </span>
        </div>
        <Button
          variant="ghost"
          className="!px-2"
          title="Refresh configuration"
          onClick={async () => {
            try {
              await api.refreshConfig()
              await queryClient.invalidateQueries()
              toast.push({
                kind: 'success',
                title: 'Configuration refreshed',
                description: 'YAML registries reloaded from disk.',
              })
            } catch (err) {
              toast.push({
                kind: 'error',
                title: 'Refresh failed',
                description: err instanceof Error ? err.message : 'Unknown error',
              })
            }
          }}
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
        <Button variant="ghost" className="!px-2" onClick={toggle} title="Toggle theme">
          {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </header>
  )
}
