import { useMemo } from 'react'
import { CommandPalette } from './CommandPalette'
import type { Command } from '../lib/commands'
import { useHub } from '../lib/hub'
import type { HubModule } from '../lib/hubQuery'

/** Hub-aware command palette (M9-F5 + M14-F3): module navigation + slash commands.
 *  Lives inside <HubProvider> so it can read slash commands and route them. */
export function AppCommandPalette({
  open,
  onClose,
  modules
}: {
  open: boolean
  onClose: () => void
  modules: readonly { id: string; label: string }[]
}) {
  const hub = useHub()

  const commands = useMemo<Command[]>(() => {
    const goto: Command[] = modules.map((m) => ({
      id: `goto-${m.id}`,
      title: m.label,
      hint: 'Go to',
      keywords: m.id,
      run: () => hub.navigate(m.id as HubModule)
    }))
    const slash: Command[] = hub.slashCommands.map((c) => ({
      id: `cmd-${c.name}`,
      title: `/${c.name}`,
      hint: c.description || 'Command',
      group: 'Commands',
      keywords: c.name,
      run: () => hub.runSlashCommand(c)
    }))
    return [...goto, ...slash]
  }, [modules, hub])

  return <CommandPalette open={open} onClose={onClose} commands={commands} />
}
