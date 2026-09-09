import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { cn } from '@/utils/cn'

type ModalSize = 'md' | 'lg' | 'xl' | 'full'

const SIZE_CLASS: Record<ModalSize, string> = {
  md: 'max-w-2xl',
  lg: 'max-w-4xl',
  xl: 'max-w-5xl',
  full: 'max-w-6xl',
}

/** Stack id of the topmost open modal (Escape closes only the top). */
let topModalStackId = 0
let nextModalStackId = 0

export function Modal({
  open,
  onClose,
  title,
  description,
  path,
  children,
  footer,
  headerExtra,
  toolbar,
  size = 'xl',
  labelledBy,
  closeOnBackdrop = true,
  className,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  path?: ReactNode
  children: ReactNode
  footer?: ReactNode
  /** Right side of header (beside close), e.g. Save / Revert */
  headerExtra?: ReactNode
  /** Optional strip under header (file chips, tabs) */
  toolbar?: ReactNode
  size?: ModalSize
  labelledBy?: string
  closeOnBackdrop?: boolean
  className?: string
}) {
  const autoId = useId()
  const titleId = labelledBy || `app-modal-title-${autoId}`
  const stackIdRef = useRef(0)
  const [zIndex, setZIndex] = useState(50)

  useLayoutEffect(() => {
    if (!open) return

    nextModalStackId += 1
    stackIdRef.current = nextModalStackId
    topModalStackId = nextModalStackId
    setZIndex(50 + nextModalStackId * 10)

    return () => {
      if (topModalStackId === stackIdRef.current) {
        topModalStackId = Math.max(0, stackIdRef.current - 1)
      }
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && stackIdRef.current === topModalStackId) {
        e.stopPropagation()
        onClose()
      }
    }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = prev
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 flex items-center justify-center p-4 sm:p-6"
      style={{ zIndex }}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/60 backdrop-blur-[1px]"
        aria-label="Close dialog"
        onClick={closeOnBackdrop ? onClose : undefined}
      />
      <div
        className={cn(
          'relative z-10 flex max-h-[90vh] w-full flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] shadow-2xl shadow-black/40',
          SIZE_CLASS[size],
          className,
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold tracking-tight">
              {title}
            </h2>
            {description ? (
              <p className="mt-1 text-sm text-[var(--fg-muted)]">{description}</p>
            ) : null}
            {path ? (
              <p className="mt-1 break-all font-mono text-[11px] text-[var(--fg-muted)]">{path}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {headerExtra}
            <Button variant="ghost" className="!px-2" onClick={onClose} title="Close">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {toolbar ? (
          <div className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-3">
            {toolbar}
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-auto">{children}</div>

        {footer !== undefined ? (
          <div className="flex justify-end gap-2 border-t border-[var(--border)] px-5 py-3">
            {footer}
          </div>
        ) : (
          <div className="flex justify-end border-t border-[var(--border)] px-5 py-3">
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
