import { useTheme } from '@/app/theme'
import { Button } from '@/components/ui/Button'
import { Panel, PanelHeader } from '@/components/ui/Panel'

export function SettingsPage() {
  const { theme, setTheme } = useTheme()
  return (
    <Panel className="mx-auto max-w-lg">
      <PanelHeader title="Settings" description="Local portal preferences" />
      <div className="space-y-4 p-5">
        <div>
          <p className="text-sm font-medium">Appearance</p>
          <div className="mt-2 flex gap-2">
            <Button
              variant={theme === 'light' ? 'primary' : 'secondary'}
              onClick={() => setTheme('light')}
            >
              Light
            </Button>
            <Button
              variant={theme === 'dark' ? 'primary' : 'secondary'}
              onClick={() => setTheme('dark')}
            >
              Dark
            </Button>
          </div>
        </div>
        <p className="text-xs text-[var(--fg-muted)]">
          Theme is stored in localStorage (`iep-theme`). API secrets are never loaded in the
          browser.
        </p>
      </div>
    </Panel>
  )
}
