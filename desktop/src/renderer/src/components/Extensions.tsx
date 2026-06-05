import { useState } from 'react'
import { Blocks, SlashSquare, Webhook, Sparkles } from 'lucide-react'
import type { Conn } from '../lib/api'
import { cn } from '../lib/cn'
import { Page } from './ui/Page'
import { McpServers } from './extensions/McpServers'
import { HooksPanel } from './extensions/HooksPanel'
import { SkillsLibrary } from './extensions/SkillsLibrary'
import { CommandsPanel } from './extensions/CommandsPanel'

const TABS = [
  { id: 'mcp', label: 'MCP Servers', icon: Blocks },
  { id: 'commands', label: 'Commands', icon: SlashSquare },
  { id: 'hooks', label: 'Hooks', icon: Webhook },
  { id: 'skills', label: 'Skills', icon: Sparkles }
] as const

type Tab = (typeof TABS)[number]['id']

/** M14 — Extensibility hub (F1/F4/F5 + command management). One place to connect
 *  MCP servers, define slash commands, configure hooks and manage skills. */
export function Extensions({ conn }: { conn: Conn }) {
  const [tab, setTab] = useState<Tab>('mcp')

  return (
    <Page
      title="Extensions"
      subtitle="MCP servers, slash commands, hooks and skills — tools that serve chat and the agent."
    >
      <div className="mb-6 flex gap-1 border-b border-border">
        {TABS.map((t) => {
          const Icon = t.icon
          const active = t.id === tab
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
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

      {tab === 'mcp' ? <McpServers conn={conn} /> : null}
      {tab === 'commands' ? <CommandsPanel conn={conn} /> : null}
      {tab === 'hooks' ? <HooksPanel conn={conn} /> : null}
      {tab === 'skills' ? <SkillsLibrary conn={conn} /> : null}
    </Page>
  )
}
