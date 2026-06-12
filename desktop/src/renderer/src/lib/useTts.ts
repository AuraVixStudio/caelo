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
  // S35-c: epoka żądania — dwa szybkie „Read aloud" nie mogą zagrać dwóch audio naraz
  // (drugie speak pauzuje audioRef, ale 1. request mógł być jeszcze w trakcie await; ten
  // licznik unieważnia poprzedni in-flight TTS — ostatni klik wygrywa).
  const reqRef = useRef(0)

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
      const myReq = ++reqRef.current // unieważnia każdy wcześniejszy in-flight request
      if (speakingRef.current === idx) {
        setSpeakingIdx(null) // klik w aktywny = stop
        return
      }
      setSpeakingIdx(idx)
      try {
        const r = await textToSpeech(conn, { text: content, voice_id: voiceRef.current })
        if (reqRef.current !== myReq) return // nowszy speak ubiegł ten — nie odtwarzaj
        const audio = playBase64Audio(r.audio_b64, r.mime)
        audioRef.current = audio
        audio.onended = () => {
          if (reqRef.current !== myReq) return
          audioRef.current = null
          setSpeakingIdx((cur) => (cur === idx ? null : cur))
        }
      } catch {
        if (reqRef.current === myReq) setSpeakingIdx(null)
      }
    },
    [conn]
  )

  return { speakingIdx, speak }
}
