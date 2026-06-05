// Typ współdzielony z procesem głównym (zob. desktop/src/main/index.ts).
// Zduplikowany świadomie: renderer nie importuje modułów Node z `main`.
export interface CoreConnection {
  status: 'starting' | 'ready' | 'error' | 'stopped'
  baseUrl?: string
  token?: string
  port?: number
  version?: string
  error?: string
}

declare global {
  interface Window {
    caelo: {
      getCore: () => Promise<CoreConnection>
      onCoreStatus: (callback: (status: CoreConnection) => void) => () => void
      selectFolder: () => Promise<string | null>
      openPath: (path: string) => Promise<string>
    }
  }
}
