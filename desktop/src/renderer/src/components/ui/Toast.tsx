import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react'
import { cn } from '../../lib/cn'

// ROAD-4.1-d: jeden wspólny kanał komunikatów (toast) — likwiduje „klasę cichych
// porażek" (Ctrl+S, odmowa mikrofonu, błąd STT, odrzucone załączniki szły dotąd w
// pustkę lub tylko do console). Wzorowany na pasku błędu z ChatView. Hooki w lib/
// wołają `useToast().push(...)`; bez providera `push` jest no-opem (testy jednostkowe
// hooków nie muszą owijać się w provider).

export type ToastTone = 'info' | 'success' | 'error'
export interface ToastItem {
  id: number
  message: string
  tone: ToastTone
}
export interface ToastApi {
  push: (message: string, tone?: ToastTone) => void
}

const NOOP: ToastApi = { push: () => undefined }
export const ToastContext = createContext<ToastApi | null>(null)

/** Dostęp do wspólnego kanału komunikatów. Brak providera → no-op (bez wywrotki). */
export function useToast(): ToastApi {
  return useContext(ToastContext) ?? NOOP
}

const AUTO_DISMISS_MS = 6000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const idRef = useRef(0)

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (message: string, tone: ToastTone = 'info') => {
      const id = ++idRef.current
      setItems((prev) => [...prev, { id, message, tone }])
      setTimeout(() => dismiss(id), AUTO_DISMISS_MS)
    },
    [dismiss]
  )
  // Stabilna tożsamość API (push jest useCallback'em) — konsumenci typu useWorkspace
  // mogą trzymać `toast` w deps useCallback bez tracenia memoizacji.
  const api = useMemo(() => ({ push }), [push])

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2"
        role="region"
        aria-label="Notifications"
      >
        {items.map((t) => (
          <button
            key={t.id}
            type="button"
            role="status"
            onClick={() => dismiss(t.id)}
            className={cn(
              'pointer-events-auto rounded-lg border bg-surface px-3 py-2 text-left text-sm shadow-[var(--shadow)] outline-none focus-visible:ring-2 focus-visible:ring-accent',
              t.tone === 'error'
                ? 'border-error/40 text-error'
                : t.tone === 'success'
                  ? 'border-success/40 text-success'
                  : 'border-border text-fg'
            )}
          >
            {t.message}
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
