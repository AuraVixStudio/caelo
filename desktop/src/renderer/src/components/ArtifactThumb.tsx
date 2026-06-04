import { useEffect, useState } from 'react'
import { getArtifactContentUrl, type Conn } from '../lib/api'
import { cn } from '../lib/cn'

/** Miniatura artefaktu-obrazu (M9-F4). Treść `/content` wymaga nagłówka Bearer, więc
 *  pobieramy bajty jako blob object URL (jak `getArtifactContentUrl`) i zwalniamy go
 *  przy odmontowaniu. Błąd/ładowanie → neutralny placeholder. */
export function ArtifactThumb({
  conn,
  artifactId,
  alt,
  className
}: {
  conn: Conn
  artifactId: string
  alt?: string
  className?: string
}) {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    getArtifactContentUrl(conn, artifactId)
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
  }, [conn, artifactId])

  if (!url) return <div className={cn('bg-surface-2', className)} aria-hidden="true" />
  return <img src={url} alt={alt ?? ''} className={cn('object-cover', className)} />
}
