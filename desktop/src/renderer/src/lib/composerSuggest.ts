// Composer autocomplete for the Code agent — slash commands ("/") and file
// references ("@path"). Pure helpers (no React/DOM) so they're unit-testable.
//
// - Slash: a leading "/name" still being typed (no space yet), like the chat composer.
//   On pick, the command template is expanded (handled by the caller, reusing slashCommands).
// - File: an "@token" ending at the caret (no whitespace inside). On pick, the token is
//   replaced with "@<path> " so the agent can read_file the referenced path.

export interface SuggestToken {
  kind: 'slash' | 'file'
  query: string
  start: number // index of the trigger char ('/' or '@') in the text
  end: number // caret index (end of the token)
}

/** Decide whether an autocomplete is active given the text and caret position. */
export function detectSuggest(text: string, caret: number): SuggestToken | null {
  // Slash command: the whole input is a leading "/name" with no space yet.
  const sm = /^\/([a-zA-Z0-9_-]*)$/.exec(text)
  if (sm) return { kind: 'slash', query: sm[1], start: 0, end: text.length }
  // File reference: "@token" immediately before the caret, token has no whitespace.
  const before = text.slice(0, Math.max(0, caret))
  const fm = /(?:^|\s)@([^\s@]*)$/.exec(before)
  if (fm) {
    const start = before.length - fm[1].length - 1 // index of '@'
    return { kind: 'file', query: fm[1], start, end: caret }
  }
  return null
}

/** Fuzzy-rank workspace files for an "@" query (basename match beats path match). */
export function fuzzyFiles(files: string[], query: string, limit = 8): string[] {
  const q = query.trim().toLowerCase()
  if (!q) return files.slice(0, limit)
  const base = (p: string): string => p.slice(p.lastIndexOf('/') + 1).toLowerCase()
  return files
    .map((p, i) => {
      const lp = p.toLowerCase()
      const b = base(p)
      let s = 0
      if (b === q) s = 4
      else if (b.startsWith(q)) s = 3
      else if (b.includes(q)) s = 2
      else if (lp.includes(q)) s = 1
      return { p, i, s }
    })
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.p.length - b.p.length || a.i - b.i)
    .slice(0, limit)
    .map((x) => x.p)
}

/** Replace the active "@token" with "@<path> " and return the new text + caret. */
export function applyFileSuggest(
  text: string,
  tok: SuggestToken,
  path: string
): { text: string; caret: number } {
  const head = text.slice(0, tok.start)
  const tail = text.slice(tok.end)
  const insert = `@${path} `
  return { text: head + insert + tail, caret: head.length + insert.length }
}
