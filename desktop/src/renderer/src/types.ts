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

export interface NativeReferenceItem {
  id: string
  name: string
  mime: string
  bytes: number
  updatedAt: number
  uri: string
}

export interface CoreRequestInput {
  path: string
  method?: string
  body?: string
  headers?: Record<string, string>
  timeoutMs?: number
}

export interface CoreRequestResult {
  ok: boolean
  status: number
  data?: unknown
  error?: string
}

declare global {
  interface Window {
    caelo: {
      getCore: () => Promise<CoreConnection>
      coreRequest: (request: CoreRequestInput) => Promise<CoreRequestResult>
      onCoreStatus: (callback: (status: CoreConnection) => void) => () => void
      selectFolder: () => Promise<string | null>
      openPath: (path: string) => Promise<string>
      listReferenceLibrary: () => Promise<NativeReferenceItem[]>
      importReferenceLibrary: () => Promise<NativeReferenceItem[]>
      getReferenceDataUri: (id: string) => Promise<string>
      deleteReferenceImage: (id: string) => Promise<boolean>
    }
  }
}
