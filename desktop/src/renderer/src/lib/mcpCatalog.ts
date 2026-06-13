// Faza-G/TOP4: czysta logika katalogu MCP — podstawianie inputów wpisu (ścieżka/klucz) w
// gotową konfigurację serwera. Trzymane osobno od McpServers (testowalne bez renderu).
import type { McpCatalogEntry, McpServerInput } from './api'

/** Klucze wymaganych inputów, które są jeszcze puste (Add zablokowany, dopóki niepuste). */
export function missingRequired(entry: McpCatalogEntry, values: Record<string, string>): string[] {
  return (entry.inputs ?? [])
    .filter((i) => i.required && !(values[i.key] ?? '').trim())
    .map((i) => i.key)
}

/**
 * Wpis katalogu + wartości inputów → `McpServerInput` gotowy do `addMcpServer`.
 * 'arg' podstawia wartość w miejsce tokenu `{key}` w command; 'env' ustawia env[env_key].
 * Zawsze `enabled: false` — TOP4: install != autostart (start to osobna, potwierdzana akcja).
 */
export function resolveCatalogEntry(
  entry: McpCatalogEntry,
  values: Record<string, string>
): McpServerInput {
  const env: Record<string, string> = { ...(entry.env ?? {}) }
  let command = entry.command ? [...entry.command] : undefined
  for (const inp of entry.inputs ?? []) {
    const v = (values[inp.key] ?? '').trim()
    if (!v) continue
    if (inp.target === 'arg' && command) {
      command = command.map((tok) => (tok === `{${inp.key}}` ? v : tok))
    } else if (inp.target === 'env' && inp.env_key) {
      env[inp.env_key] = v
    }
  }
  return {
    id: entry.id,
    name: entry.name,
    transport: entry.transport,
    command,
    env: Object.keys(env).length ? env : undefined,
    url: entry.url,
    enabled: false
  }
}

/** Podgląd komendy (z podstawionymi argami) do consentu w UI — bez wartości env (sekretów). */
export function commandPreview(entry: McpCatalogEntry, values: Record<string, string>): string {
  if (entry.transport === 'remote') return entry.url ?? ''
  return (resolveCatalogEntry(entry, values).command ?? []).join(' ')
}
