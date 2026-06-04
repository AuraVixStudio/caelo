// Paleta komend (M9-F5) — model komendy + czyste filtrowanie/ranking. Bez React/DOM
// → testowalne w Vitest. Komenda niesie akcję `run` (wykonanie poza tym utilem).

export interface Command {
  id: string
  title: string
  /** Krótka etykieta po prawej (np. „Go to"). */
  hint?: string
  /** Grupa (np. „Navigate") — opcjonalna, do nagłówków. */
  group?: string
  /** Dodatkowe słowa kluczowe do dopasowania (niewyświetlane). */
  keywords?: string
  run: () => void
}

function score(c: Command, q: string): number {
  const title = c.title.toLowerCase()
  if (title === q) return 100
  if (title.startsWith(q)) return 60
  if (title.includes(q)) return 40
  const hay = `${c.hint ?? ''} ${c.group ?? ''} ${c.keywords ?? ''}`.toLowerCase()
  if (hay.includes(q)) return 20
  return 0
}

/** Przefiltruj i posortuj komendy po zapytaniu. Puste `query` → wszystkie (bez zmiany
 *  kolejności). Dopasowanie po tytule (najsilniej) i polach pomocniczych. Stabilne
 *  przy remisie (zachowuje wejściową kolejność). */
export function filterCommands(commands: Command[], query: string): Command[] {
  const q = query.trim().toLowerCase()
  if (!q) return commands
  return commands
    .map((c, i) => ({ c, i, s: score(c, q) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.c)
}
