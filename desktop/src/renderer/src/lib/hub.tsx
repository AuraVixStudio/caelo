// Wspólny stan kręgosłupa huba (M9-F1/F2/F6): nawigacja między trybami, „pending
// send" (artefakt → wejście trybu) oraz stan projektu (wspólny scope historii).
// Cienki kontekst — buduje na nim Send-to (F2), History (F3) i przełącznik projektu (F6).

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction
} from 'react'
import {
  createProject as apiCreateProject,
  listProjects,
  selectProject as apiSelectProject,
  type Conn,
  type HubProject,
  type InputBlock
} from './api'
import type { HubModule } from './hubQuery'

export interface PendingSend {
  /** Moduł docelowy, który ma podnieść `block` jako wejście. */
  target: HubModule
  /** Gotowy blok wejściowy z send-to bus (M9-B4). */
  block: InputBlock
  /** Krótka etykieta źródła (np. nazwa pliku) do podglądu w composerze. */
  label?: string
  /** Opcjonalny prompt do wstawienia (np. „Describe this image"). */
  prompt?: string
}

/** Zdjęcie wystawione (drop/upload/„Send to") w panelu Image/Video. Trzymane w
 *  Hub (a nie w stanie panelu), bo panele są leniwe i ODMONTOWUJĄ się przy zmianie
 *  zakładki — bez tego dodane zdjęcie znikałoby po przełączeniu trybu. */
export interface StagedImage {
  name: string
  uri: string // data-URI (upload/drop) lub https URL (z magistrali Send-to)
}

interface HubState {
  /** Przełącz aktywny moduł (App podpina `setActive`). */
  navigate: (m: HubModule) => void
  /** Oczekujący transfer artefaktu do trybu docelowego (Send-to). */
  pendingSend: PendingSend | null
  setPendingSend: (p: PendingSend | null) => void
  /** Ustaw transfer i od razu przejdź do trybu docelowego (skrót dla F2). */
  sendTo: (p: PendingSend) => void

  // --- Staged media (M11): przetrwają zmianę zakładki (panele są leniwe) ---
  /** Referencje obrazu w panelu Image (edycja/warianty, do 3). */
  imageRefs: StagedImage[]
  setImageRefs: Dispatch<SetStateAction<StagedImage[]>>
  /** Kadr startowy w panelu Video (image→video). */
  videoFrame: StagedImage | null
  setVideoFrame: Dispatch<SetStateAction<StagedImage | null>>
  /** Źródłowe wideo w panelu Video (edit/extend). `uri` = data:video/* lub https URL. */
  videoSource: StagedImage | null
  setVideoSource: Dispatch<SetStateAction<StagedImage | null>>
  /** Jednorazowa komenda zmiany trybu Video (z „Send video to…"). */
  videoCommandMode: 'edit' | 'extend' | null
  setVideoCommandMode: Dispatch<SetStateAction<'edit' | 'extend' | null>>
  /** Załaduj wideo jako źródło i przejdź do panelu Video w danym trybie (M11). */
  sendVideoToVideo: (v: { name: string; uri: string; mode: 'edit' | 'extend' }) => void

  // --- Projekty (F6): wspólny scope historii/artefaktów ---
  projects: HubProject[]
  recentWorkspaces: string[]
  currentProjectId: string | null
  projectsLoading: boolean
  selectProject: (id: string | null) => Promise<void>
  createProject: (name: string, root?: string) => Promise<void>
  reloadProjects: () => void
}

const HubContext = createContext<HubState | null>(null)

export function HubProvider({
  conn,
  navigate,
  children
}: {
  conn: Conn | null
  navigate: (m: HubModule) => void
  children: ReactNode
}) {
  const [pendingSend, setPendingSend] = useState<PendingSend | null>(null)
  const [imageRefs, setImageRefs] = useState<StagedImage[]>([])
  const [videoFrame, setVideoFrame] = useState<StagedImage | null>(null)
  const [videoSource, setVideoSource] = useState<StagedImage | null>(null)
  const [videoCommandMode, setVideoCommandMode] = useState<'edit' | 'extend' | null>(null)
  const [projects, setProjects] = useState<HubProject[]>([])
  const [recentWorkspaces, setRecentWorkspaces] = useState<string[]>([])
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null)
  const [projectsLoading, setProjectsLoading] = useState(false)

  const reloadProjects = useCallback(() => {
    if (!conn) return
    setProjectsLoading(true)
    listProjects(conn)
      .then((r) => {
        setProjects(r.projects)
        setRecentWorkspaces(r.recent_workspaces)
        setCurrentProjectId(r.current_project_id)
      })
      .catch(() => undefined)
      .finally(() => setProjectsLoading(false))
  }, [conn])

  useEffect(() => {
    reloadProjects()
  }, [reloadProjects])

  const selectProject = useCallback(
    async (id: string | null) => {
      if (!conn) return
      const r = await apiSelectProject(conn, id)
      setCurrentProjectId(r.current_project_id)
    },
    [conn]
  )

  const createProject = useCallback(
    async (name: string, root?: string) => {
      if (!conn) return
      const r = await apiCreateProject(conn, name, root)
      setCurrentProjectId(r.current_project_id)
      reloadProjects() // odśwież listę o nowy projekt
    },
    [conn, reloadProjects]
  )

  const value = useMemo<HubState>(
    () => ({
      navigate,
      pendingSend,
      setPendingSend,
      sendTo: (p: PendingSend) => {
        setPendingSend(p)
        navigate(p.target)
      },
      imageRefs,
      setImageRefs,
      videoFrame,
      setVideoFrame,
      videoSource,
      setVideoSource,
      videoCommandMode,
      setVideoCommandMode,
      sendVideoToVideo: (v: { name: string; uri: string; mode: 'edit' | 'extend' }) => {
        setVideoSource({ name: v.name, uri: v.uri })
        setVideoCommandMode(v.mode)
        navigate('Video')
      },
      projects,
      recentWorkspaces,
      currentProjectId,
      projectsLoading,
      selectProject,
      createProject,
      reloadProjects
    }),
    [
      navigate,
      pendingSend,
      imageRefs,
      videoFrame,
      videoSource,
      videoCommandMode,
      projects,
      recentWorkspaces,
      currentProjectId,
      projectsLoading,
      selectProject,
      createProject,
      reloadProjects
    ]
  )

  return <HubContext.Provider value={value}>{children}</HubContext.Provider>
}

export function useHub(): HubState {
  const ctx = useContext(HubContext)
  if (!ctx) throw new Error('useHub must be used within <HubProvider>')
  return ctx
}
