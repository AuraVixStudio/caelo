import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fsGetWorkspace,
  fsRead,
  fsSetWorkspace,
  fsWrite,
  gitStatus,
  type Conn
} from './api'

export interface EditorTab {
  path: string
  content: string
  dirty: boolean
}

/**
 * Warstwa danych modułu Code (P2-3): katalog roboczy, gałąź Git, otwarte
 * zakładki edytora i odświeżanie drzewa. Spina ze sobą sprzężone operacje
 * (zmiana workspace czyści zakładki; zapis odświeża Git; tura agenta przeładowuje
 * niezmodyfikowane zakładki), wcześniej rozsiane po ~390-liniowym CodeView.
 * `treeKey`/`gitKey` to liczniki wymuszające remount FileTree/GitPanel.
 */
export function useWorkspace(conn: Conn): {
  workspacePath: string | null
  branch: string
  treeKey: number
  gitKey: number
  tabs: EditorTab[]
  activePath: string | null
  active: EditorTab | null
  setActivePath: (path: string | null) => void
  refreshGit: () => void
  selectWorkspace: (picked: string) => Promise<void>
  openFolder: () => Promise<void>
  openFile: (path: string) => Promise<void>
  changeContent: (path: string, content: string) => void
  closeTab: (path: string) => void
  saveActive: () => Promise<void>
  onFilesChanged: () => Promise<void>
} {
  const [workspacePath, setWorkspacePath] = useState<string | null>(null)
  const [branch, setBranch] = useState<string>('')
  const [treeKey, setTreeKey] = useState(0)
  const [gitKey, setGitKey] = useState(0)
  const [tabs, setTabs] = useState<EditorTab[]>([])
  const [activePath, setActivePath] = useState<string | null>(null)

  const tabsRef = useRef<EditorTab[]>([])
  tabsRef.current = tabs

  function refreshGit(): void {
    void gitStatus(conn)
      .then((s) => setBranch(s.is_repo ? s.branch || '' : ''))
      .catch(() => setBranch(''))
    setGitKey((k) => k + 1)
  }

  useEffect(() => {
    void fsGetWorkspace(conn)
      .then((r) => {
        if (r.path) {
          setWorkspacePath(r.path)
          setTreeKey((k) => k + 1)
          refreshGit()
        }
      })
      .catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function selectWorkspace(picked: string): Promise<void> {
    try {
      await fsSetWorkspace(conn, picked)
      setWorkspacePath(picked)
      setTabs([])
      setActivePath(null)
      setTreeKey((k) => k + 1)
      refreshGit()
    } catch (e) {
      // P1-6: nie połykaj po cichu wyboru workspace przez użytkownika.
      console.error('Failed to set workspace:', e)
    }
  }

  async function openFolder(): Promise<void> {
    const picked = await window.caelo.selectFolder()
    if (picked) await selectWorkspace(picked)
  }

  // Stabilny (P2-4): trafia jako `onOpen` do zmemoizowanych węzłów FileTree, więc
  // nie może zmieniać tożsamości między renderami. `conn` jest stały w czasie życia
  // CodeView; resztę bierze z ref/setterów (stabilne).
  const openFile = useCallback(
    async (path: string): Promise<void> => {
      const existing = tabsRef.current.find((t) => t.path === path)
      if (existing) {
        setActivePath(path)
        return
      }
      try {
        const r = await fsRead(conn, path)
        setTabs((prev) => [...prev, { path, content: r.content, dirty: false }])
        setActivePath(path)
      } catch {
        /* ignore */
      }
    },
    [conn]
  )

  function changeContent(path: string, content: string): void {
    setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, content, dirty: true } : t)))
  }

  function closeTab(path: string): void {
    setTabs((prev) => prev.filter((t) => t.path !== path))
    if (activePath === path) {
      const rest = tabsRef.current.filter((t) => t.path !== path)
      setActivePath(rest.length ? rest[rest.length - 1].path : null)
    }
  }

  async function saveActive(): Promise<void> {
    const tab = tabsRef.current.find((t) => t.path === activePath)
    if (!tab) return
    try {
      await fsWrite(conn, tab.path, tab.content)
      setTabs((prev) => prev.map((t) => (t.path === tab.path ? { ...t, dirty: false } : t)))
      refreshGit()
    } catch {
      /* ignore */
    }
  }

  // Po turze agenta: odśwież drzewo, Git i przeładuj niezmodyfikowane zakładki.
  async function onFilesChanged(): Promise<void> {
    setTreeKey((k) => k + 1)
    refreshGit()
    for (const t of tabsRef.current) {
      if (t.dirty) continue
      try {
        const r = await fsRead(conn, t.path)
        setTabs((prev) => prev.map((x) => (x.path === t.path ? { ...x, content: r.content } : x)))
      } catch {
        /* ignore */
      }
    }
  }

  const active = tabs.find((t) => t.path === activePath) || null

  return {
    workspacePath,
    branch,
    treeKey,
    gitKey,
    tabs,
    activePath,
    active,
    setActivePath,
    refreshGit,
    selectWorkspace,
    openFolder,
    openFile,
    changeContent,
    closeTab,
    saveActive,
    onFilesChanged
  }
}
