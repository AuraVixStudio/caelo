// Pomocniki audio dla głosu: nagrywanie z mikrofonu (STT), kodowanie base64,
// odtwarzanie wyniku TTS. Realtime (PCM streaming) jest w lib/realtime.ts.

export interface Recording {
  blob: Blob
  mime: string
}

/** Prosty rejestrator mikrofonu oparty o MediaRecorder (na potrzeby STT). */
export class MicRecorder {
  private rec: MediaRecorder | null = null
  private chunks: BlobPart[] = []
  private stream: MediaStream | null = null

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : ''
    this.rec = mime
      ? new MediaRecorder(this.stream, { mimeType: mime })
      : new MediaRecorder(this.stream)
    this.chunks = []
    this.rec.ondataavailable = (e) => {
      if (e.data.size) this.chunks.push(e.data)
    }
    this.rec.start()
  }

  stop(): Promise<Recording> {
    return new Promise((resolve, reject) => {
      const rec = this.rec
      if (!rec) {
        reject(new Error('Not recording'))
        return
      }
      rec.onstop = () => {
        const mime = rec.mimeType || 'audio/webm'
        const blob = new Blob(this.chunks, { type: mime })
        this.cleanup()
        resolve({ blob, mime })
      }
      rec.stop()
    })
  }

  cancel(): void {
    try {
      this.rec?.stop()
    } catch {
      /* ignore */
    }
    this.cleanup()
  }

  private cleanup(): void {
    this.stream?.getTracks().forEach((t) => t.stop())
    this.stream = null
    this.rec = null
    this.chunks = []
  }
}

/** Base64 (bez prefiksu data:) z ArrayBuffer — w kawałkach, by nie przepełnić stosu. */
export function arrayBufferToBase64(buf: ArrayBufferLike): string {
  const bytes = new Uint8Array(buf)
  let bin = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(bin)
}

export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes.buffer
}

export async function blobToBase64(blob: Blob): Promise<string> {
  return arrayBufferToBase64(await blob.arrayBuffer())
}

/** Odtwarza audio z base64 (np. wynik TTS). Zwraca element <audio> (do zatrzymania). */
export function playBase64Audio(b64: string, mime = 'audio/mpeg'): HTMLAudioElement {
  const audio = new Audio(`data:${mime};base64,${b64}`)
  void audio.play().catch(() => undefined)
  return audio
}
