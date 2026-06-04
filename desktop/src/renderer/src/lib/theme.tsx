import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from 'react'

export type ThemeMode = 'light' | 'dark' | 'system'
type Resolved = 'light' | 'dark'

const STORAGE_KEY = 'grok.theme'

interface ThemeCtx {
  theme: ThemeMode
  resolved: Resolved
  setTheme: (mode: ThemeMode) => void
}

const Ctx = createContext<ThemeCtx | null>(null)

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function readStored(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    /* ignore */
  }
  return 'system'
}

function resolve(mode: ThemeMode): Resolved {
  if (mode === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return mode
}

/** Nakłada/zdejmuje klasę `.dark` na <html> — synchronicznie, bez migotania. */
function applyClass(resolved: Resolved): void {
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')
  root.style.colorScheme = resolved
}

// Zastosuj zapisany motyw natychmiast przy ładowaniu modułu (przed pierwszym paintem).
if (typeof document !== 'undefined') {
  applyClass(resolve(readStored()))
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(() => readStored())
  const [resolved, setResolved] = useState<Resolved>(() => resolve(theme))

  const setTheme = useCallback((mode: ThemeMode) => {
    setThemeState(mode)
    try {
      localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      /* ignore */
    }
    const r = resolve(mode)
    setResolved(r)
    applyClass(r)
  }, [])

  // Śledź zmianę motywu systemowego, gdy wybrano „system".
  useEffect(() => {
    if (theme !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (): void => {
      const r: Resolved = mq.matches ? 'dark' : 'light'
      setResolved(r)
      applyClass(r)
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])

  const value = useMemo<ThemeCtx>(() => ({ theme, resolved, setTheme }), [theme, resolved, setTheme])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
