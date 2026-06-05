import { useEffect, useState } from 'react'
import { getArtifactContentUrl, type Conn, type HubArtifact } from '../lib/api'
import { cn } from '../lib/cn'

/** Podgląd artefaktu obrazu/wideo (M11-F4). Treść `/content` wymaga nagłówka Bearer,
 *  więc pobieramy bajty jako blob object URL i zwalniamy go przy odmontowaniu.
 *
 *  Wideo: pokazujemy pierwszą klatkę od razu (element <video> z załadowanym blobem
 *  renderuje klatkę 0 jako poster — bez autoplay) i używamy `object-contain`, by
 *  zachować oryginalne proporcje w karcie ORAZ na pełnym ekranie (object-cover
 *  przycinał/zoomował w fullscreenie). Obraz zostaje `object-cover` (równe miniatury). */
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
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
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
  }, [conn, art.id])

  if (!url) return <div className={cn('animate-pulse bg-surface-2', className)} aria-hidden="true" />

  return isVideo ? (
    <video src={url} controls preload="metadata" className={cn('bg-black object-contain', className)} />
  ) : (
    <img src={url} alt="" loading="lazy" className={cn('object-cover', className)} />
  )
}
