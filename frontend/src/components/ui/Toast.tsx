import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { X } from 'lucide-react'
import { cn } from '@/utils/cn'

type ToastKind = 'success' | 'error' | 'info'
type ToastItem = { id: string; title: string; description?: string; kind: ToastKind }

const ToastContext = createContext<{ push: (t: Omit<ToastItem, 'id'>) => void } | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const push = useCallback((toast: Omit<ToastItem, 'id'>) => {
    const id = crypto.randomUUID()
    setItems((prev) => [...prev, { ...toast, id }])
    window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 4200)
  }, [])
  const value = useMemo(() => ({ push }), [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-full max-w-sm flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            className={cn(
              'pointer-events-auto rounded-md border px-4 py-3 shadow-lg backdrop-blur',
              'border-[var(--border)] bg-[var(--bg-elevated)] text-[var(--fg)]',
              t.kind === 'success' && 'border-l-4 border-l-[var(--color-ok)]',
              t.kind === 'error' && 'border-l-4 border-l-[var(--color-danger)]',
              t.kind === 'info' && 'border-l-4 border-l-[var(--accent)]',
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">{t.title}</p>
                {t.description ? (
                  <p className="mt-0.5 text-xs text-[var(--fg-muted)]">{t.description}</p>
                ) : null}
              </div>
              <button
                type="button"
                className="text-[var(--fg-muted)] hover:text-[var(--fg)]"
                onClick={() => setItems((prev) => prev.filter((x) => x.id !== t.id))}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
