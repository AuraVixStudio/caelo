import { useCallback, useRef, useState } from 'react'

/** S35-i: czy kontener jest „przy dole" (w granicy `threshold` px). Czysta funkcja. */
export function isNearBottom(
  m: { scrollHeight: number; scrollTop: number; clientHeight: number },
  threshold = 80
): boolean {
  return m.scrollHeight - m.scrollTop - m.clientHeight < threshold
}

/**
 * Stick-to-bottom (S35-i): auto-scroll TYLKO gdy user jest blisko dołu — inaczej nie
 * wyrywaj go z czytanej historii i pokaż „Jump to bottom". `scrollRef` podpinasz do
 * przewijanego kontenera, `onScroll` do jego `onScroll`; `scrollToBottom(force)` w efekcie
 * dosuwającym (force=true omija strażnik, np. dla karty approval w AgentPanel).
 */
export function useStickToBottom(): {
  scrollRef: React.MutableRefObject<HTMLDivElement | null>
  atBottom: boolean
  onScroll: () => void
  scrollToBottom: (force?: boolean) => void
} {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const atBottomRef = useRef(true)
  const [atBottom, setAtBottom] = useState(true)

  const onScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const near = isNearBottom(el)
    atBottomRef.current = near
    setAtBottom(near)
  }, [])

  const scrollToBottom = useCallback((force = false) => {
    const el = scrollRef.current
    if (!el) return
    if (force || atBottomRef.current) {
      el.scrollTop = el.scrollHeight
      atBottomRef.current = true
      setAtBottom(true)
    }
  }, [])

  return { scrollRef, atBottom, onScroll, scrollToBottom }
}
