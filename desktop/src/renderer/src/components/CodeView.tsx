import { useEffect, useState } from 'react'
import { Group, Panel, useDefaultLayout } from 'react-resizable-panels'
import { ChevronDown, Clock, FolderOpen, GitBranch, RotateCw, Shield, SquareTerminal, X } from 'lucide-react'
import { clearPermissions, fsRecent, getPermissions, type Conn } from '../lib/api'
import { saveSettings, useModels } from '../lib/serverState'
import { useWorkspace } from '../lib/useWorkspace'
import { cn } from '../lib/cn'
import { FileTree } from './code/FileTree'
import { CodeEditor } from './code/CodeEditor'
import { Terminal } from './code/Terminal'
import { AgentPanel } from './code/AgentPanel'
import { GitPanel } from './code/GitPanel'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Popover } from './ui/Popover'
import { ResizeHandle } from './ui/ResizeHandle'

const norm = (p: string): string => p.replace(/\\/g, '/')
const baseName = (p: string): string => norm(p).split('/').filter(Boolean).pop() || p

export function CodeView({ conn }: { conn: Conn }) {
  const [showTerminal, setShowTerminal] = useState(false)
  const [showGit, setShowGit] = useState(false)
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState<string>('grok-build-0.1')
  const { models: modelsResp } = useModels(conn) // P2-2: współdzielony cache /models

  // P2-3: katalog roboczy, zakładki edytora i Git wydzielone do useWorkspace.
  const ws = useWorkspace(conn)

  const hLayout = useDefaultLayout({ id: 'grok.code' })
  const vLayout = useDefaultLayout({ id: 'grok.code.center' })

  // P2-2: modele ze współdzielonego cache.
  useEffect(() => {
    if (!modelsResp) return
    setModels(modelsResp.chat)
    setModel(modelsResp.default_code || 'grok-build-0.1')
  }, [modelsResp])

  // Skróty: Ctrl+S zapis, Ctrl+` terminal, Ctrl+Shift+G panel Git.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent): void => {
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 's') {
        e.preventDefault()
        void ws.saveActive()
      } else if (mod && e.key === '`') {
        e.preventDefault()
        setShowTerminal((v) => !v)
      } else if (mod && e.shiftKey && e.key.toLowerCase() === 'g') {
        e.preventDefault()
        setShowGit((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws.activePath])

  function onModelChange(m: string): void {
    setModel(m)
    void saveSettings(conn, { code_model: m }).catch(() => undefined)
  }

  const editorPane = (
    <>
      <div className="flex shrink-0 items-stretch overflow-x-auto border-b border-border bg-surface">
        {ws.tabs.map((t) => (
          // P2-6: realne <button>y (otwarcie / zamknięcie) zamiast klikalnego <div>.
          <div
            key={t.path}
            className={cn(
              'group flex items-center gap-1 whitespace-nowrap border-r border-border pr-1.5 text-xs transition-colors',
              t.path === ws.activePath ? 'bg-bg text-fg' : 'text-muted hover:text-fg'
            )}
          >
            <button
              onClick={() => ws.setActivePath(t.path)}
              aria-current={t.path === ws.activePath ? 'true' : undefined}
              title={t.path}
              className="py-2 pl-3 pr-1 outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {baseName(t.path)}
              {t.dirty ? ' •' : ''}
            </button>
            <button
              onClick={() => ws.closeTab(t.path)}
              aria-label={`Close ${baseName(t.path)}`}
              className="flex h-4 w-4 items-center justify-center rounded text-muted opacity-60 outline-none transition-colors hover:bg-surface-2 hover:text-fg hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent"
            >
              <X size={12} />
            </button>
          </div>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden [&_.cm-editor]:h-full">
        {ws.active ? (
          <CodeEditor
            path={ws.active.path}
            value={ws.active.content}
            onChange={(v) => ws.changeContent(ws.active!.path, v)}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted">
            Select a file from the tree.
          </div>
        )}
      </div>
    </>
  )

  return (
    <div className="flex min-w-0 flex-1 flex-col bg-bg">
      <header className="flex h-12 shrink-0 items-center gap-1.5 border-b border-border px-3">
        <Button variant="subtle" size="sm" icon={<FolderOpen size={15} />} onClick={ws.openFolder}>
          Open Folder
        </Button>
        <Popover
          label="Recent folders"
          trigger={({ toggle, triggerProps }) => (
            <Button
              variant="ghost"
              size="sm"
              icon={<Clock size={15} />}
              onClick={toggle}
              {...triggerProps}
            >
              Recent
              <ChevronDown size={13} className="opacity-60" />
            </Button>
          )}
        >
          {(close) => (
            <RecentMenuContent
              conn={conn}
              current={ws.workspacePath}
              onPick={(p) => void ws.selectWorkspace(p)}
              close={close}
            />
          )}
        </Popover>

        <span
          className="min-w-0 flex-1 truncate font-mono text-xs text-muted"
          title={ws.workspacePath || ''}
        >
          {ws.workspacePath || 'No folder selected'}
        </span>

        {ws.branch ? (
          <span className="flex shrink-0 items-center gap-1 text-xs text-success">
            <GitBranch size={13} /> {ws.branch}
          </span>
        ) : null}

        <IconButton
          label="Git panel (Ctrl+Shift+G)"
          icon={<GitBranch size={18} />}
          active={showGit}
          tooltipSide="bottom-end"
          onClick={() => setShowGit((v) => !v)}
        />
        <IconButton
          label="Terminal (Ctrl+`)"
          icon={<SquareTerminal size={18} />}
          active={showTerminal}
          tooltipSide="bottom-end"
          onClick={() => setShowTerminal((v) => !v)}
        />
        <Popover
          align="end"
          label="Agent permissions"
          trigger={({ toggle, open, triggerProps }) => (
            <IconButton
              label="Agent permissions"
              icon={<Shield size={18} />}
              active={open}
              tooltip={!open}
              tooltipSide="bottom-end"
              onClick={toggle}
              {...triggerProps}
            />
          )}
        >
          {() => <PermissionsMenuContent conn={conn} />}
        </Popover>
      </header>

      <Group
        orientation="horizontal"
        defaultLayout={hLayout.defaultLayout}
        onLayoutChanged={hLayout.onLayoutChanged}
        className="min-h-0 flex-1"
      >
        {/* Drzewo + Git */}
        <Panel
          id="tree"
          defaultSize="18%"
          minSize="12%"
          maxSize="32%"
          collapsible
          collapsedSize="0%"
          style={{ overflow: 'hidden' }}
          className="flex min-h-0 flex-col bg-surface"
        >
          <div className="min-h-0 flex-1 overflow-auto">
            {ws.workspacePath ? (
              <FileTree
                conn={conn}
                refreshKey={ws.treeKey}
                activePath={ws.activePath}
                onOpen={ws.openFile}
              />
            ) : (
              <p className="p-3 text-xs text-muted">Open a folder to browse files.</p>
            )}
          </div>
          {ws.workspacePath && showGit ? (
            <GitPanel conn={conn} refreshKey={ws.gitKey} onCommitted={ws.onFilesChanged} />
          ) : null}
        </Panel>

        <ResizeHandle orientation="horizontal" />

        {/* Center: edytor (+ terminal) */}
        <Panel
          id="center"
          minSize="30%"
          style={{ overflow: 'hidden' }}
          className="flex min-h-0 flex-col bg-bg"
        >
          {showTerminal ? (
            <Group
              orientation="vertical"
              defaultLayout={vLayout.defaultLayout}
              onLayoutChanged={vLayout.onLayoutChanged}
              className="min-h-0 flex-1"
            >
              <Panel
                id="editor"
                minSize="20%"
                style={{ overflow: 'hidden' }}
                className="flex min-h-0 flex-col"
              >
                {editorPane}
              </Panel>
              <ResizeHandle orientation="vertical" />
              <Panel
                id="terminal"
                defaultSize="32%"
                minSize="8%"
                collapsible
                collapsedSize="0%"
                style={{ overflow: 'hidden' }}
                className="border-t border-border bg-bg"
              >
                <Terminal conn={conn} />
              </Panel>
            </Group>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">{editorPane}</div>
          )}
        </Panel>

        <ResizeHandle orientation="horizontal" />

        {/* Agent */}
        <Panel
          id="agent"
          defaultSize="28%"
          minSize="18%"
          maxSize="46%"
          collapsible
          collapsedSize="0%"
          style={{ overflow: 'hidden' }}
          className="min-h-0"
        >
          <AgentPanel
            conn={conn}
            workspacePath={ws.workspacePath}
            model={model}
            models={models}
            onModelChange={onModelChange}
            onFilesChanged={ws.onFilesChanged}
          />
        </Panel>
      </Group>
    </div>
  )
}

function RecentMenuContent({
  conn,
  current,
  onPick,
  close
}: {
  conn: Conn
  current: string | null
  onPick: (path: string) => void
  close: () => void
}) {
  const [recent, setRecent] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void fsRecent(conn)
      .then((r) => setRecent(r.recent))
      .catch(() => setRecent([]))
      .finally(() => setLoading(false))
  }, [conn])

  const cur = current ? norm(current) : ''
  const items = recent.filter((p) => norm(p) !== cur)

  if (loading) return <div className="px-2.5 py-2 text-xs text-muted">Loading…</div>
  if (items.length === 0)
    return <div className="px-2.5 py-2 text-xs text-muted">No recent folders.</div>
  return (
    <div className="flex w-72 flex-col gap-0.5">
      {items.map((p) => (
        <button
          key={p}
          title={p}
          onClick={() => {
            onPick(p)
            close()
          }}
          className="flex flex-col items-start gap-0.5 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-surface-2"
        >
          <span className="text-[13px] font-medium text-fg">{baseName(p)}</span>
          <span className="w-full truncate font-mono text-[11px] text-muted">{p}</span>
        </button>
      ))}
    </div>
  )
}

function PermissionsMenuContent({ conn }: { conn: Conn }) {
  const [rules, setRules] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  function load(): void {
    setLoading(true)
    void getPermissions(conn)
      .then((r) => setRules(r.rules))
      .catch(() => setRules([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conn])

  async function clearAll(): Promise<void> {
    try {
      await clearPermissions(conn)
      setRules([])
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="flex w-80 flex-col gap-2">
      <div className="flex items-center justify-between px-1 pt-1 text-xs font-semibold text-muted">
        <span>Always-allowed</span>
        <IconButton size="sm" label="Refresh" icon={<RotateCw size={14} />} onClick={load} />
      </div>
      {loading ? (
        <div className="px-1 text-xs text-muted">Loading…</div>
      ) : rules.length === 0 ? (
        <div className="px-1 text-xs text-muted">
          Nothing allowed yet. “Always allow” on an approval card adds a rule here.
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          {rules.map((r) => (
            <div
              key={r}
              className="break-all rounded-md bg-surface-2 px-2 py-1.5 font-mono text-xs text-fg"
            >
              {r}
            </div>
          ))}
        </div>
      )}
      <Button
        variant="danger"
        size="sm"
        className="mt-1"
        onClick={clearAll}
        disabled={rules.length === 0}
      >
        Clear all
      </Button>
    </div>
  )
}
