import { useEffect, useRef, useState } from 'react'
import { buildArtifactSrcDoc, type ArtifactLang } from '../lib/artifacts'
import { cn } from '../lib/cn'

const MIN_HEIGHT = 80
const MAX_HEIGHT = 800
const INITIAL_HEIGHT = 180

/**
 * Faza-G/TOP5: artefakt modelu (HTML/SVG) renderowany w SANDBOXOWANYM iframe (opaque origin,
 * brak dostępu do rodzica/tokenu; CSP + sandbox blokują sieć/formularze/popupy — patrz
 * lib/artifacts). Toggle Preview/Code; auto-resize z postMessage iframe (clamp do MAX_HEIGHT).
 */
export function ArtifactFrame({ lang, code }: { lang: ArtifactLang; code: string }) {
  const [view, setView] = useState<'preview' | 'code'>('preview')
  const [srcDoc, setSrcDoc] = useState(() => buildArtifactSrcDoc(lang, code))
  const [height, setHeight] = useState(INITIAL_HEIGHT)
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const firstRun = useRef(true)

  // Debounce przebudowy srcdoc: podczas streamingu kod zmienia się co token; bez tego iframe
  // przeładowywałby się na każdy delta (miganie). srcDoc jest już zbudowany na starcie (initial
  // state), więc pierwszy przebieg efektu pomijamy — przebudowa tylko po realnej zmianie kodu.
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false
      return
    }
    const t = setTimeout(() => setSrcDoc(buildArtifactSrcDoc(lang, code)), 200)
    return () => clearTimeout(t)
  }, [lang, code])

  // Auto-resize: przyjmij wysokość TYLKO z tego iframe (weryfikacja event.source) + clamp.
  useEffect(() => {
    function onMsg(e: MessageEvent): void {
      if (!iframeRef.current || e.source !== iframeRef.current.contentWindow) return
      const h = (e.data as { __caeloArtifactHeight?: unknown } | null)?.__caeloArtifactHeight
      if (typeof h === 'number' && isFinite(h) && h > 0) {
        setHeight(Math.min(Math.max(Math.ceil(h) + 4, MIN_HEIGHT), MAX_HEIGHT))
      }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-border">
      <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-2 py-1">
        <span className="text-[10px] font-medium uppercase tracking-wide text-muted">{lang}</span>
        <span className="text-[10px] text-muted">artifact</span>
        <div className="ml-auto flex items-center gap-1">
          {(['preview', 'code'] as const).map((id) => (
            <button
              key={id}
              onClick={() => setView(id)}
              className={cn(
                'rounded px-1.5 py-0.5 text-[11px] capitalize',
                view === id ? 'bg-accent/15 text-accent' : 'text-muted hover:text-fg'
              )}
            >
              {id}
            </button>
          ))}
        </div>
      </div>
      {view === 'preview' ? (
        <iframe
          ref={iframeRef}
          title={`${lang} artifact preview`}
          sandbox="allow-scripts"
          srcDoc={srcDoc}
          className="block w-full bg-white"
          style={{ height, border: 0 }}
        />
      ) : (
        <pre className="m-0 max-h-[480px] overflow-auto bg-surface p-3 text-xs">
          <code>{code}</code>
        </pre>
      )}
    </div>
  )
}
