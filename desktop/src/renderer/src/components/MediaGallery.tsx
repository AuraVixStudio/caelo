import type { MediaResult } from '../lib/api'
import { Button } from './ui/Button'

/** Siatka wyników mediów (obrazy) z przyciskiem otwarcia pliku/URL. */
export function MediaGallery({ results }: { results: MediaResult[] }) {
  if (!results.length) return null

  const open = (path: string | null, url: string): void => {
    if (path) void window.grok.openPath(path)
    else window.open(url, '_blank')
  }

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
      {results.map((r, i) => (
        <div
          key={i}
          className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-2.5 shadow-[var(--shadow)]"
        >
          <img src={r.url} alt="" loading="lazy" className="w-full rounded-lg" />
          <Button variant="outline" size="sm" onClick={() => open(r.path, r.url)}>
            {r.path ? 'Open file' : 'Open URL'}
          </Button>
        </div>
      ))}
    </div>
  )
}
