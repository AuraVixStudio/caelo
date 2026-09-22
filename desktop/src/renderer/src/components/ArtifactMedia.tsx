import { useEffect, useRef, useState } from 'react'
import { getArtifactMediaUrl, getArtifactThumbnailUrl, type Conn, type HubArtifact } from '../lib/api'
import { cn } from '../lib/cn'

/** Ile razy ponawiamy nieudane pobranie podglądu, zanim pokażemy pustą kafelkę. */
const MAX_ATTEMPTS = 3

/** Podgląd korzysta ze strumieniowego protokołu procesu głównego. Dzięki obsłudze
 * Range wideo nie jest kopiowane w całości do pamięci jako Blob.
 *
 * Dwie rzeczy są tu celowe i nie należy ich cofać:
 *  1. BRAK `loading="lazy"` — pierwowzór Caelo pobierał bajty od razu w efekcie
 *     (`<img>` dostawał gotowy blob), więc żądanie zawsze wychodziło przy montażu
 *     karty. Po przejściu na `caelo-media://` leniwe ładowanie potrafiło NIGDY nie
 *     wystartować dla świeżo dołożonej karty i miniatura pojawiała się dopiero po
 *     restarcie aplikacji. Miniatury to małe WEBP-y — ładujemy je od razu.
 *  2. Ponowienie po błędzie — protokół zwraca 503, gdy sidecar akurat nie jest
 *     „ready" (restart po crashu). Bez retry `<img>` zostawał pusty na zawsze.
 */
export function ArtifactMedia({
  conn,
  art,
  className
}: {
  conn: Conn
  art: HubArtifact
  className?: string
}) {
  void conn // połączenie jest przechowywane wyłącznie w zaufanym procesie głównym
  const isVideo = art.type === 'video' || (art.mime || '').startsWith('video/')
  const [attempt, setAttempt] = useState(0)
  const [ready, setReady] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    setAttempt(0)
    setReady(false)
  }, [art.id])

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    []
  )

  function onError(): void {
    if (attempt + 1 >= MAX_ATTEMPTS || timer.current !== null) return
    timer.current = window.setTimeout(
      () => {
        timer.current = null
        setAttempt((value) => value + 1)
      },
      400 * (attempt + 1)
    )
  }

  const base = isVideo ? getArtifactMediaUrl(art.id) : getArtifactThumbnailUrl(art.id)
  // `retry` omija cache Chromium po nieudanej próbie; `#t=0.1` każe odtwarzaczowi
  // wyszukać klatkę, dzięki czemu karta wideo pokazuje podgląd bez odtwarzania.
  const url = attempt ? `${base}?retry=${attempt}` : base

  return isVideo ? (
    <video
      key={attempt}
      src={`${url}#t=0.1`}
      controls
      preload="metadata"
      onLoadedData={() => setReady(true)}
      onError={onError}
      className={cn('bg-black object-contain', className)}
    />
  ) : (
    <img
      src={url}
      alt=""
      decoding="async"
      onLoad={() => setReady(true)}
      onError={onError}
      className={cn('object-cover', !ready && 'animate-pulse bg-surface-2', className)}
    />
  )
}
