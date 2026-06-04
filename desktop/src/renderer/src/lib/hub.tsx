// Wspólny stan kręgosłupa huba (M9-F1): nawigacja między trybami + „pending send"
// (artefakt przeniesiony do innego trybu jako wejście). Cienki kontekst — buduje na
// nim Send-to (F2), History (F3), paleta (F5) i przełącznik projektu (F6).

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { InputBlock } from './api'
import type { HubModule } from './hubQuery'

export interface PendingSend {
  /** Moduł docelowy, który ma podnieść `block` jako wejście. */
  target: HubModule
  /** Gotowy blok wejściowy z send-to bus (M9-B4). */
  block: InputBlock
  /** Krótka etykieta źródła (np. nazwa pliku/artefaktu) do podglądu w composerze. */
  label?: string
}

interface HubState {
  /** Przełącz aktywny moduł (App podpina `setActive`). */
  navigate: (m: HubModule) => void
  /** Oczekujący transfer artefaktu do trybu docelowego (Send-to). */
  pendingSend: PendingSend | null
  setPendingSend: (p: PendingSend | null) => void
  /** Ustaw transfer i od razu przejdź do trybu docelowego (wygodny skrót dla F2). */
  sendTo: (p: PendingSend) => void
}

const HubContext = createContext<HubState | null>(null)

export function HubProvider({
  navigate,
  children
}: {
  navigate: (m: HubModule) => void
  children: ReactNode
}) {
  const [pendingSend, setPendingSend] = useState<PendingSend | null>(null)

  const value = useMemo<HubState>(
    () => ({
      navigate,
      pendingSend,
      setPendingSend,
      sendTo: (p: PendingSend) => {
        setPendingSend(p)
        navigate(p.target)
      }
    }),
    [navigate, pendingSend]
  )

  return <HubContext.Provider value={value}>{children}</HubContext.Provider>
}

export function useHub(): HubState {
  const ctx = useContext(HubContext)
  if (!ctx) throw new Error('useHub must be used within <HubProvider>')
  return ctx
}
