import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MoreHorizontal, Pencil, PauseCircle, PlayCircle, Rocket } from 'lucide-react'
import { Link } from 'react-router-dom'
import { cn } from '@/utils/cn'
import type { Report } from '@/types'

type Props = {
  report: Report
  onEdit: (report: Report) => void
  onToggleEnabled: (report: Report) => void
  busy?: boolean
}

type MenuPos = { top: number; left: number; openUp: boolean }

export function ReportActionsMenu({ report, onEdit, onToggleEnabled, busy }: Props) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<MenuPos | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  const updatePosition = () => {
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const menuWidth = 192
    const menuHeight = menuRef.current?.offsetHeight ?? 140
    const gap = 6
    const spaceBelow = window.innerHeight - rect.bottom
    const openUp = spaceBelow < menuHeight + gap && rect.top > spaceBelow
    const left = Math.min(
      Math.max(8, rect.right - menuWidth),
      window.innerWidth - menuWidth - 8,
    )
    const top = openUp ? rect.top - gap - menuHeight : rect.bottom + gap
    setPos({ top: Math.max(8, top), left, openUp })
  }

  useLayoutEffect(() => {
    if (!open) {
      setPos(null)
      return
    }
    updatePosition()
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onReposition = () => updatePosition()
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', onReposition)
    window.addEventListener('scroll', onReposition, true)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', onReposition)
      window.removeEventListener('scroll', onReposition, true)
    }
  }, [open])

  const menu =
    open && pos
      ? createPortal(
          <div
            ref={menuRef}
            id={menuId}
            role="menu"
            style={{ top: pos.top, left: pos.left }}
            className="fixed z-[80] w-48 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-elevated)] py-1 shadow-lg shadow-black/30"
          >
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[var(--fg)] hover:bg-[var(--bg)]"
              onClick={() => {
                setOpen(false)
                onEdit(report)
              }}
            >
              <Pencil className="h-3.5 w-3.5 text-[var(--fg-muted)]" />
              Edit
            </button>
            <Link
              role="menuitem"
              to="/pipeline/run"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[var(--fg)] hover:bg-[var(--bg)]"
              onClick={() => setOpen(false)}
            >
              <Rocket className="h-3.5 w-3.5 text-[var(--fg-muted)]" />
              Run in pipeline
            </Link>
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-[var(--fg)] hover:bg-[var(--bg)]"
              onClick={() => {
                setOpen(false)
                onToggleEnabled(report)
              }}
            >
              {report.enabled ? (
                <>
                  <PauseCircle className="h-3.5 w-3.5 text-[var(--fg-muted)]" />
                  Pause
                </>
              ) : (
                <>
                  <PlayCircle className="h-3.5 w-3.5 text-[var(--fg-muted)]" />
                  Activate
                </>
              )}
            </button>
          </div>,
          document.body,
        )
      : null

  return (
    <div className="relative" onClick={(e) => e.stopPropagation()}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        title="Report actions"
        disabled={busy}
        className={cn(
          'inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--fg-muted)]',
          'hover:bg-[var(--bg)] hover:text-[var(--fg)]',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]',
          'disabled:opacity-50',
        )}
        onClick={() => setOpen((v) => !v)}
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {menu}
    </div>
  )
}
