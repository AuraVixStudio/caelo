import { useEffect, useRef, useState } from 'react'
import {
  streamChat,
  type ChatStreamHandle,
  type ChatStreamHandlers,
  type ChatStreamPayload,
  type Conn
} from './api'

/**
 * Mechanika streamingu czatu (P2-3): trzyma `streaming` + uchwyt strumienia,
 * resetuje je w `onDone`/`onError` i — w odróżnieniu od dawnego ChatView —
 * **przerywa strumień przy odmontowaniu** (przełączenie modułu nie zostawia
 * osieroconego streamu aktualizującego odmontowany komponent).
 */
export function useChatStream(conn: Conn): {
  streaming: boolean
  start: (req: ChatStreamPayload, handlers: ChatStreamHandlers) => void
  stop: () => void
} {
  const [streaming, setStreaming] = useState(false)
  const ref = useRef<ChatStreamHandle | null>(null)

  useEffect(() => {
    return () => {
      ref.current?.stop()
      ref.current = null
    }
  }, [])

  function start(req: ChatStreamPayload, handlers: ChatStreamHandlers): void {
    setStreaming(true)
    ref.current = streamChat(conn, req, {
      onDelta: handlers.onDelta,
      // M10-F1/F2/F6: forward live-search activity, sources and usage as-is.
      onTool: handlers.onTool,
      onCitations: handlers.onCitations,
      onUsage: handlers.onUsage,
      onDone: (full) => {
        handlers.onDone(full)
        setStreaming(false)
        ref.current = null
      },
      onError: (err) => {
        handlers.onError(err)
        setStreaming(false)
        ref.current = null
      }
    })
  }

  function stop(): void {
    ref.current?.stop()
  }

  return { streaming, start, stop }
}
