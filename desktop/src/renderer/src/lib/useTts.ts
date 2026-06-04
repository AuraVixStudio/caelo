import { useCallback, useEffect, useRef, useState } from 'react'
import { textToSpeech, type Conn } from './api'
import { playBase64Audio } from './audio'

/**
 * Czytanie wiadomości na głos (TTS). `speak` jest **stabilny** (useCallback +
 * refy na głos/aktualny indeks), dzięki czemu zmemoizowane wiersze czatu (P2-4)
 * nie odświeżają się przy każdym tiku. `speakingIdx` wskazuje aktualnie czytaną
 * wiadomość; ponowny klik w nią zatrzymuje odtwarzanie. Pauza przy odmontowaniu.
 */
export function useTts(
  conn: Conn,
  voice: string
): { speakingIdx: number | null; speak: (idx: number, content: string) => Promise<void> } {
  const [speakingIdx, setSpeakingIdx] = useState<number | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const voiceRef = useRef(voice)
  voiceRef.current = voice
  const speakingRef = useRef<number | null>(null)
  speakingRef.current = speakingIdx

  useEffect(() => {
    return () => {
      try {
        audioRef.current?.pause()
      } catch {
        /* ignore */
      }
    }
  }, [])

  const speak = useCallback(
    async (idx: number, content: string): Promise<void> => {
      if (audioRef.current) {
        try {
          audioRef.current.pause()
        } catch {
          /* ignore */
        }
        audioRef.current = null
      }
      if (speakingRef.current === idx) {
        setSpeakingIdx(null) // klik w aktywny = stop
        return
      }
      setSpeakingIdx(idx)
      try {
        const r = await textToSpeech(conn, { text: content, voice_id: voiceRef.current })
        const audio = playBase64Audio(r.audio_b64, r.mime)
        audioRef.current = audio
        audio.onended = () => {
          audioRef.current = null
          setSpeakingIdx((cur) => (cur === idx ? null : cur))
        }
      } catch {
        setSpeakingIdx(null)
      }
    },
    [conn]
  )

  return { speakingIdx, speak }
}
