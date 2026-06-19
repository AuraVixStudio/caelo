import { useEffect, useMemo, useRef, useState } from 'react'
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

  // Najświeższe convos dla flushu przy odmontowaniu (osobny efekt niżej nie zależy od convos).
  const convosRef = useRef(convos)
  convosRef.current = convos

  // Utrwalanie z debounce (koniec generacji / bezczynność). Czyści `saveError` po
  // udanym zapisie (P1-I/g1 — wcześniej baner „storage full" zostawał na zawsze).
  useEffect(() => {
    if (!convos.length) return
    const t = setTimeout(() => {
      setSaveError(
        saveConversations(convos)
          ? null
          : 'Could not save chat history (browser storage is full).'
      )
    }, 800)
    return () => clearTimeout(t)
  }, [convos])

  // FLUSH przy odmontowaniu / twardym zamknięciu okna (P1-I). Osobny efekt z pustymi
  // zależnościami — jego cleanup NIE odpala się na każdą zmianę convos (debounce wyżej
  // zachowany), tylko przy realnym unmount. Bez tego clearTimeout gubił oczekujący zapis
  // (lazy unmount modułu czatu / zamknięcie apki = utrata całej tury). localStorage jest
  // synchroniczne, więc flush jest tani. pagehide/beforeunload bo cleanup efektu NIE jest
  // gwarantowany przy niszczeniu okna Electron.
  useEffect(() => {
    const onHide = (): void => {
      // NIE nadpisuj zapisanych rozmów PUSTĄ tablicą. `convos` jest [] tylko ZANIM
      // efekt init wczyta dane (a w dev StrictMode robi mount→unmount→mount: cleanup
      // flusha odpala się, gdy convosRef wciąż = [] z initial useState). Bez tego guardu
      // flush przy odmontowaniu (lazy unmount modułu czatu / podwójny mount) zapisywał []
      // i KASOWAŁ całą historię. Po init `convos` ma zawsze ≥1 (init tworzy „New chat",
      // delete też), więc pusta lista nigdy nie jest stanem do utrwalenia.
      if (convosRef.current.length === 0) return
      saveConversations(convosRef.current)
    }
    window.addEventListener('pagehide', onHide)
    window.addEventListener('beforeunload', onHide)
    return () => {
      onHide()
      window.removeEventListener('pagehide', onHide)
      window.removeEventListener('beforeunload', onHide)
    }
  }, [])

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
    // P1-I/g2: licz next/activeId POZA updaterem setConvos — updater musi być czysty
    // (React 19 StrictMode podwójnie go wywołuje; setActiveId w środku = anti-pattern).
    const next = convos.filter((c) => c.id !== id)
    const list = next.length ? next : [newConversation()]
    setConvos(list)
    if (id === activeId) setActiveId(list[0].id)
  }

  return { convos, activeId, active, saveError, setActiveId, patchActive, createChat, deleteChat }
}
