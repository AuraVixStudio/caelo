import { useEffect, useState } from 'react'
import { Film, Play } from 'lucide-react'
import { getArtifactContentUrl, type Conn, type HubArtifact } from '../lib/api'
import { cn } from '../lib/cn'

/** Podgląd artefaktu obrazu/wideo (M11-F4). Treść `/content` wymaga nagłówka Bearer,
 *  więc pobieramy bajty jako blob object URL i zwalniamy go przy odmontowaniu.
 *
 *  Wideo jest LENIWE: dopóki user nie kliknie „play", pokazujemy lekki placeholder
 *  (galeria mogłaby inaczej pobrać dziesiątki pełnych plików wideo naraz). */
export function ArtifactMedia({
  conn,
  art,
  className
}: {
  conn: Conn
  art: HubArtifact
  className?: string
}) {
  const isVideo = art.type === 'video' || (art.mime || '').startsWith('video/')
  const [load, setLoad] = useState(!isVideo) // obrazy ładujemy od razu, wideo na żądanie
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!load) return
    let active = true
    let objectUrl: string | null = null
    getArtifactContentUrl(conn, art.id)
      .then((u) => {
        if (active) {
          objectUrl = u
          setUrl(u)
        } else {
          URL.revokeObjectURL(u)
        }
      })
      .catch(() => undefined)
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [conn, art.id, load])

  if (isVideo && !load) {
    return (
      <button
        type="button"
        onClick={() => setLoad(true)}
        className={cn(
          'flex flex-col items-center justify-center gap-1.5 bg-surface-2 text-muted transition-colors hover:text-fg',
          className
        )}
      >
        <Film size={22} />
        <span className="inline-flex items-center gap-1 text-xs">
          <Play size={12} /> Preview
        </span>
      </button>
    )
  }

  if (!url) return <div className={cn('animate-pulse bg-surface-2', className)} aria-hidden="true" />

  return isVideo ? (
    <video src={url} controls autoPlay className={cn('bg-black object-cover', className)} />
  ) : (
    <img src={url} alt="" loading="lazy" className={cn('object-cover', className)} />
  )
}
