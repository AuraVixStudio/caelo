// Slash commands (M14-F3) — pure helpers (no React/DOM → testable in Vitest).
// The composer detects a leading "/", shows matching commands, and on selection
// expands the command's template with the user's input.

export interface SlashCommandLite {
  name: string
  description?: string
  template: string
  target?: string
  mode?: string
  action?: string
  builtin?: boolean
}

function rank(name: string, q: string): number {
  const n = name.toLowerCase()
  if (n === q) return 3
  if (n.startsWith(q)) return 2
  if (n.includes(q)) return 1
  return 0
}

/** Filter + rank commands by a query (with or without a leading "/"). Empty → all. */
export function filterSlashCommands<T extends { name: string; description?: string }>(
  commands: T[],
  query: string
): T[] {
  const q = query.trim().toLowerCase().replace(/^\//, '')
  if (!q) return commands
  return commands
    .map((c, i) => ({ c, i, s: Math.max(rank(c.name, q), (c.description ?? '').toLowerCase().includes(q) ? 1 : 0) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.c)
}

/** If `text` is a slash command still being typed (no space yet, e.g. "/pl"),
 *  return the partial name (may be ""); otherwise null. Used to toggle the dropdown. */
export function slashQuery(text: string): string | null {
  const m = /^\/([a-zA-Z0-9_-]*)$/.exec(text)
  return m ? m[1] : null
}

/** Parse a full slash invocation "/name rest" → { name, rest }, or null. */
export function matchSlash(text: string): { name: string; rest: string } | null {
  const m = /^\/([a-zA-Z0-9_-]+)(?:\s+([\s\S]*))?$/.exec(text)
  if (!m) return null
  return { name: m[1], rest: m[2] ?? '' }
}

/** Client-side template expansion — mirrors the backend `expand()` ({input}/{args}). */
export function expandTemplate(template: string, input: string): string {
  const t = (input ?? '').trim()
  return template.split('{input}').join(t).split('{args}').join(t).trim()
}
