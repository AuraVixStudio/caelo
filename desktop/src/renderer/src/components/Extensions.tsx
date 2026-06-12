import { useEffect, useState, type KeyboardEvent } from 'react'
import { Blocks, FileCode, SlashSquare, Store, Users, Webhook, Sparkles } from 'lucide-react'
import { getSandboxStatus, type Conn, type SandboxStatus } from '../lib/api'
import { cn } from '../lib/cn'
import { Page } from './ui/Page'
import { McpServers } from './extensions/McpServers'
import { LspServers } from './extensions/LspServers'
import { HooksPanel } from './extensions/HooksPanel'
import { SkillsLibrary } from './extensions/SkillsLibrary'
import { CommandsPanel } from './extensions/CommandsPanel'
import { SubagentsPanel } from './extensions/SubagentsPanel'
import { Marketplace } from './extensions/Marketplace'

const TABS = [
  { id: 'mcp', label: 'MCP Servers', icon: Blocks },
  { id: 'lsp', label: 'Language Servers', icon: FileCode },
  { id: 'commands', label: 'Commands', icon: SlashSquare },
  { id: 'hooks', label: 'Hooks', icon: Webhook },
  { id: 'skills', label: 'Skills', icon: Sparkles },
  { id: 'subagents', label: 'Subagents', icon: Users },
  { id: 'marketplace', label: 'Marketplace', icon: Store }
] as const

type Tab = (typeof TABS)[number]['id']

// S35-m: ARIA tabs — stabilne id zakładki/panelu do powiązania (aria-controls/labelledby).
const tabId = (id: string): string => `ext-tab-${id}`
const panelId = (id: string): string => `ext-panel-${id}`

/** M14 — Extensibility hub (F1/F4/F5 + command management). One place to connect
 *  MCP servers, define slash commands, configure hooks and manage skills. */
export function Extensions({ conn }: { conn: Conn }) {
  const [tab, setTab] = useState<Tab>('mcp')
  // S34-d: ostrzeż, gdy profil sandboxa ≠ off, a OS-sandbox jest niedostępny (np. Windows) —
  // user mógłby zakładać izolację, której `wrap()` tam NIE daje (cichy no-op).
  const [sandbox, setSandbox] = useState<SandboxStatus | null>(null)
  useEffect(() => {
    let on = true
    void getSandboxStatus(conn)
      .then((s) => {
        if (on) setSandbox(s)
      })
      .catch(() => undefined)
    return () => {
      on = false
    }
  }, [conn])
  const sandboxWarn = !!sandbox && sandbox.profile !== 'off' && !sandbox.availability.available

  // S35-m: strzałki ←/→ przełączają zakładki (wzorzec WAI-ARIA tabs) + roving tabindex.
  function onTabKey(e: KeyboardEvent<HTMLButtonElement>, idx: number): void {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const dir = e.key === 'ArrowRight' ? 1 : -1
    const next = TABS[(idx + dir + TABS.length) % TABS.length]
    setTab(next.id)
    document.getElementById(tabId(next.id))?.focus()
  }

  return (
    <Page
      title="Extensions"
      subtitle="MCP servers, slash commands, hooks, skills — and a marketplace to share them."
    >
      {sandboxWarn ? (
        <div className="mb-4 rounded-lg border border-warn/40 px-3 py-2 text-sm text-warn">
          OS sandbox unavailable on {sandbox?.availability.platform} — relying on the workspace
          sandbox + tree-kill only.
        </div>
      ) : null}

      <div className="mb-6 flex gap-1 border-b border-border" role="tablist" aria-label="Extensions">
        {TABS.map((t, idx) => {
          const Icon = t.icon
          const active = t.id === tab
          return (
            <button
              key={t.id}
              id={tabId(t.id)}
              role="tab"
              aria-selected={active}
              aria-controls={panelId(t.id)}
              tabIndex={active ? 0 : -1}
              onClick={() => setTab(t.id)}
              onKeyDown={(e) => onTabKey(e, idx)}
              className={cn(
                'flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'border-accent text-accent'
                  : 'border-transparent text-muted hover:text-fg'
              )}
            >
              <Icon size={15} />
              {t.label}
            </button>
          )
        })}
      </div>

      <div role="tabpanel" id={panelId(tab)} aria-labelledby={tabId(tab)}>
        {tab === 'mcp' ? <McpServers conn={conn} /> : null}
        {tab === 'lsp' ? <LspServers conn={conn} /> : null}
        {tab === 'commands' ? <CommandsPanel conn={conn} /> : null}
        {tab === 'hooks' ? <HooksPanel conn={conn} /> : null}
        {tab === 'skills' ? <SkillsLibrary conn={conn} /> : null}
        {tab === 'subagents' ? <SubagentsPanel conn={conn} /> : null}
        {tab === 'marketplace' ? <Marketplace conn={conn} /> : null}
      </div>
    </Page>
  )
}
