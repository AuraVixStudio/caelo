import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import {
  Code2,
  History as HistoryIcon,
  Image as ImageIcon,
  MessageSquare,
  Mic,
  PanelLeftClose,
  PanelLeftOpen,
  Settings as SettingsIcon,
  Sparkles,
  Video as VideoIcon
} from 'lucide-react'
import { useConnection } from './lib/useConnection'
import { HubProvider } from './lib/hub'
import { cn } from './lib/cn'
import { Placeholder } from './components/Placeholder'
import { ErrorBoundary } from './components/ErrorBoundary'
import { CommandPalette } from './components/CommandPalette'
import type { Command } from './lib/commands'
import { IconButton } from './components/ui/IconButton'
import { Tooltip } from './components/ui/Tooltip'
import { ThemeToggle } from './components/ui/ThemeToggle'
import type { CoreConnection } from './types'
import type { Conn } from './lib/api'

// P2-4: code-splitting — moduły ciągną ciężkie zależności (CodeMirror/xterm w Code,
// react-markdown/highlight.js w Chat/Agent). React.lazy odracza je z bundla startowego;
// chunk ładuje się dopiero przy pierwszym wejściu w moduł (lokalnie, więc szybko).
const ChatView = lazy(() => import('./components/ChatView').then((m) => ({ default: m.ChatView })))
const CodeView = lazy(() => import('./components/CodeView').then((m) => ({ default: m.CodeView })))
const Image = lazy(() => import('./components/Image').then((m) => ({ default: m.Image })))
const Video = lazy(() => import('./components/Video').then((m) => ({ default: m.Video })))
const Voice = lazy(() => import('./components/Voice').then((m) => ({ default: m.Voice })))
const History = lazy(() => import('./components/History').then((m) => ({ default: m.History })))
const Settings = lazy(() => import('./components/Settings').then((m) => ({ default: m.Settings })))

const MODULES = [
  { id: 'Chat', label: 'Chat', icon: MessageSquare },
  { id: 'Code', label: 'Code', icon: Code2 },
  { id: 'Image', label: 'Image', icon: ImageIcon },
  { id: 'Video', label: 'Video', icon: VideoIcon },
  { id: 'Voice', label: 'Voice', icon: Mic },
  { id: 'History', label: 'History', icon: HistoryIcon },
  { id: 'Settings', label: 'Settings', icon: SettingsIcon }
] as const

type Module = (typeof MODULES)[number]['id']

const STATUS: Record<CoreConnection['status'], { label: string; dot: string }> = {
  starting: { label: 'Starting backend…', dot: 'bg-warn' },
  ready: { label: 'Connected', dot: 'bg-success' },
  error: { label: 'Connection error', dot: 'bg-error' },
  stopped: { label: 'Backend stopped', dot: 'bg-muted' }
}

const RAIL_KEY = 'grok.rail.collapsed'

/** Loader treści podczas doczytywania chunku leniwego modułu (P2-4). */
function ModuleFallback() {
  return (
    <main className="flex flex-1 items-center justify-center p-10">
      <span className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-accent" />
    </main>
  )
}

function moduleFor(active: Module, c: Conn, conn: CoreConnection) {
  switch (active) {
    case 'Chat':
      return <ChatView conn={c} />
    case 'Code':
      return <CodeView conn={c} />
    case 'Image':
      return <Image conn={c} />
    case 'Video':
      return <Video conn={c} />
    case 'Voice':
      return <Voice conn={c} />
    case 'History':
      return <History conn={c} />
    case 'Settings':
      return <Settings conn={c} />
    default:
      return <Placeholder name={active} conn={conn} />
  }
}

export default function App() {
  const [active, setActive] = useState<Module>('Chat')
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(RAIL_KEY) === '1'
    } catch {
      return false
    }
  })
  const conn = useConnection()
  const ready = conn.status === 'ready' && !!conn.baseUrl && !!conn.token
  // Stabilna tożsamość Conn (baseUrl+token) — przekazywana do HubProvider; bez
  // memoizacji nowy obiekt co render zapętlałby efekt ładujący projekty.
  const c = useMemo<Conn | null>(
    () => (ready ? { baseUrl: conn.baseUrl!, token: conn.token! } : null),
    [ready, conn.baseUrl, conn.token]
  )

  useEffect(() => {
    try {
      localStorage.setItem(RAIL_KEY, collapsed ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [collapsed])

  // M9-F5: paleta komend (Ctrl/Cmd-K) — szybki skok do dowolnego trybu.
  const [paletteOpen, setPaletteOpen] = useState(false)
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const commands = useMemo<Command[]>(
    () =>
      MODULES.map((m) => ({
        id: `goto-${m.id}`,
        title: m.label,
        hint: 'Go to',
        keywords: m.id,
        run: () => setActive(m.id)
      })),
    []
  )

  function renderModule() {
    if (!ready || !c) {
      // P2-11: pełnoekranowy wskaźnik stanu backendu (także przy padzie/reconnect w
      // trakcie sesji — App podmienia moduł, gdy połączenie znika). `aria-live` ogłasza
      // zmiany czytnikom ekranu; spinner sygnalizuje trwający restart.
      return (
        <main role="status" aria-live="polite" className="flex flex-1 items-center justify-center p-10">
          <div className="text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-2">
              {conn.status === 'starting' ? (
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-accent" />
              ) : (
                <span className={cn('h-3 w-3 rounded-full', STATUS[conn.status].dot)} />
              )}
            </div>
            <h1 className="text-lg font-semibold">{STATUS[conn.status].label}</h1>
            {conn.error ? <p className="mt-2 text-sm text-error">{conn.error}</p> : null}
          </div>
        </main>
      )
    }
    // Per-module boundary: a crash in one module shows a fallback in the content
    // area instead of blanking the window; switching modules (resetKeys) recovers it.
    // Suspense (P2-4): pokaż loader, gdy chunk leniwego modułu się doczytuje.
    return (
      <ErrorBoundary label={active} resetKeys={[active]}>
        <Suspense fallback={<ModuleFallback />}>{moduleFor(active, c, conn)}</Suspense>
      </ErrorBoundary>
    )
  }

  const status = STATUS[conn.status]

  return (
    <HubProvider conn={c} navigate={(m) => setActive(m as Module)}>
    <div className="flex h-screen overflow-hidden bg-bg text-fg">
      <aside
        className={cn(
          'flex h-full shrink-0 flex-col gap-1 border-r border-border bg-surface p-3',
          'transition-[width] duration-200 ease-out',
          collapsed ? 'w-[68px]' : 'w-60'
        )}
      >
        {/* Brand */}
        <div className="flex h-12 items-center gap-2.5 px-1.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-fg">
            <Sparkles size={18} />
          </span>
          {!collapsed ? <span className="truncate text-[15px] font-semibold">Grok Desktop</span> : null}
        </div>

        {/* Nav */}
        <nav className="mt-2 flex flex-1 flex-col gap-1">
          {MODULES.map((m) => {
            const Icon = m.icon
            const isActive = m.id === active
            const button = (
              <button
                key={m.id}
                onClick={() => setActive(m.id)}
                aria-current={isActive ? 'page' : undefined}
                className={cn(
                  'flex h-9 items-center gap-3 rounded-lg text-sm font-medium transition-colors',
                  collapsed ? 'w-9 justify-center px-0' : 'px-2.5',
                  isActive
                    ? 'bg-accent/12 text-accent'
                    : 'text-muted hover:bg-surface-2 hover:text-fg'
                )}
              >
                <Icon size={18} className="shrink-0" />
                {!collapsed ? <span className="truncate">{m.label}</span> : null}
              </button>
            )
            return collapsed ? (
              <Tooltip key={m.id} label={m.label} side="right">
                {button}
              </Tooltip>
            ) : (
              button
            )
          })}
        </nav>

        {/* Footer */}
        <div className="mt-auto flex flex-col gap-2 border-t border-border pt-3">
          <div
            className={cn(
              'flex items-center gap-2 px-1.5 text-xs text-muted',
              collapsed && 'justify-center px-0'
            )}
          >
            <span className={cn('h-2 w-2 shrink-0 rounded-full', status.dot)} />
            {!collapsed ? <span className="truncate">{status.label}</span> : null}
          </div>
          <div className={cn('flex items-center', collapsed ? 'flex-col gap-1' : 'justify-between')}>
            <ThemeToggle align={collapsed ? 'start' : 'start'} side="top" />
            <IconButton
              label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              tooltipSide="right"
              icon={collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
              onClick={() => setCollapsed((v) => !v)}
            />
          </div>
        </div>
      </aside>

      {renderModule()}
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={commands}
      />
    </div>
    </HubProvider>
  )
}
