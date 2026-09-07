import { Construction } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { Panel } from '@/components/ui/Panel'

export function PlaceholderPage({ feature, phase = 3 }: { feature: string; phase?: number }) {
  return (
    <Panel className="mx-auto max-w-xl p-8 text-center">
      <Construction className="mx-auto h-10 w-10 text-[var(--accent)]" />
      <h2 className="mt-4 text-xl font-semibold">{feature}</h2>
      <p className="mt-2 text-sm text-[var(--fg-muted)]">
        This surface is wired in the navigation shell. Full functionality lands in Phase {phase}.
      </p>
      <div className="mt-6 flex justify-center gap-2">
        <Link to="/">
          <Button variant="secondary">Dashboard</Button>
        </Link>
        <Link to="/pipeline/run">
          <Button>Run Pipeline</Button>
        </Link>
      </div>
    </Panel>
  )
}
