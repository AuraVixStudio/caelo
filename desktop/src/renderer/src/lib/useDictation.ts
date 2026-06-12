import { useEffect, useRef, useState } from 'react'
import { speechToText, type Conn } from './api'
import { blobToBase64, MicRecorder } from './audio'
import { useToast } from '../components/ui/Toast'

/** Wstrzyknij dyktowany tekst do istniejącego pola (M12-F1): dokleja po spacji,
 *  bez wiodącej spacji dla pustego pola. Czysta funkcja — wspólna dla czatu/agenta. */
export function appendDictation(prev: string, text: string): string {
  const t = text.trim()
  if (!t) return prev
  return (prev ? prev.trimEnd() + ' ' : '') + t
}

/**
 * Dyktowanie promptu przez mikrofon (P2-3, STT). Toggle: start nagrywania →
 * kolejny toggle zatrzymuje, transkrybuje (speechToText) i oddaje tekst przez
 * `onText`. Nagrywanie jest anulowane przy odmontowaniu.
 */
export function useDictation(
  conn: Conn,
  onText: (text: string) => void
): { recording: boolean; busy: boolean; toggle: () => Promise<void> } {
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const toast = useToast() // S35-j: odmowa mikrofonu / błąd STT nie mogą iść w pustkę
  const recorderRef = useRef<MicRecorder | null>(null)
  // onText przez ref — handler stabilny, zawsze świeży callback.
  const onTextRef = useRef(onText)
  onTextRef.current = onText

  useEffect(() => {
    return () => {
      recorderRef.current?.cancel()
    }
  }, [])

  async function toggle(): Promise<void> {
    if (busy) return
    if (recording) {
      const rec = recorderRef.current
      recorderRef.current = null
      setRecording(false)
      if (!rec) return
      setBusy(true)
      try {
        const { blob } = await rec.stop()
        const audio_b64 = await blobToBase64(blob)
        const r = await speechToText(conn, { audio_b64, filename: 'speech.webm' })
        const t = (r.text || '').trim()
        if (t) onTextRef.current(t)
      } catch {
        toast.push('Could not transcribe audio. Please try again.', 'error')
      } finally {
        setBusy(false)
      }
    } else {
      const rec = new MicRecorder()
      try {
        await rec.start()
        recorderRef.current = rec
        setRecording(true)
      } catch {
        toast.push('Microphone access was denied or unavailable.', 'error')
      }
    }
  }

  return { recording, busy, toggle }
}
