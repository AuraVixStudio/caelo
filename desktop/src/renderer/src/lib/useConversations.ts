import { useEffect, useMemo, useState } from 'react'
import {
  loadActiveId,
  loadConversations,
  newConversation,
  saveActiveId,
  saveConversations,
  type Conversation
} from './storage'

/**
 * Lista rozmów czatu (P2-3): inicjalizacja z localStorage, utrwalanie z
 * **debounce 800 ms** (P1-7 — nie zapisuj na każdą deltę streamu) z widocznym
 * `saveError` przy przekroczeniu limitu, oraz CRUD (`createChat`/`deleteChat`/
 * `patchActive`). `active` to memoizowana bieżąca rozmowa.
 */
export function useConversations(): {
  convos: Conversation[]
  activeId: string
  active: Conversation | null
  saveError: string | null
  setActiveId: (id: string) => void
  patchActive: (updater: (c: Conversation) => Conversation) => void
  createChat: (projectId?: string | null) => void
  deleteChat: (id: string) => void
} {
  const [convos, setConvos] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string>('')
  const [saveError, setSaveError] = useState<string | null>(null)

  // Inicjalizacja z localStorage.
  useEffect(() => {
    let list = loadConversations()
    if (list.length === 0) list = [newConversation()]
    const wanted = loadActiveId()
    const active = wanted && list.find((c) => c.id === wanted) ? wanted : list[0].id
    setConvos(list)
    setActiveId(active)
  }, [])

  // Utrwalanie z debounce (koniec generacji / bezczynność).
  useEffect(() => {
    if (!convos.length) return
    const t = setTimeout(() => {
      if (!saveConversations(convos)) {
        setSaveError('Could not save chat history (browser storage is full).')
      }
    }, 800)
    return () => clearTimeout(t)
  }, [convos])

  useEffect(() => {
    if (activeId) saveActiveId(activeId)
  }, [activeId])

  const active = useMemo(() => convos.find((c) => c.id === activeId) || null, [convos, activeId])

  function patchActive(updater: (c: Conversation) => Conversation): void {
    setConvos((prev) => prev.map((c) => (c.id === activeId ? updater(c) : c)))
  }

  function createChat(projectId?: string | null): void {
    const c = newConversation(projectId)
    setConvos((prev) => [c, ...prev])
    setActiveId(c.id)
  }

  function deleteChat(id: string): void {
    setConvos((prev) => {
      const next = prev.filter((c) => c.id !== id)
      const list = next.length ? next : [newConversation()]
      if (id === activeId) setActiveId(list[0].id)
      return list
    })
  }

  return { convos, activeId, active, saveError, setActiveId, patchActive, createChat, deleteChat }
}
