import type { CoreConnection } from '../types'

/**
 * DEV-only: atrapa mostka `window.caelo`, gdy renderer działa w zwykłej przeglądarce
 * (podgląd wyglądu UI bez Electrona). Importowana wyłącznie pod gałęzią
 * `import.meta.env.DEV && !window.caelo`, więc nie trafia do produkcyjnego bundla
 * i nigdy nie nadpisuje prawdziwego mostka z preloadu Electrona.
 */
export function installBrowserMock(): void {
  const conn: CoreConnection = {
    status: 'ready',
    baseUrl: 'http://127.0.0.1:9',
    token: 'preview',
    port: 9,
    version: 'preview'
  }
  window.caelo = {
    getCore: () => Promise.resolve(conn),
    coreRequest: async (request) => {
      try {
        const response = await fetch(conn.baseUrl + request.path, {
          method: request.method,
          body: request.body,
          // Prawdziwy most (preload → main) dokłada token sesji; bez niego podgląd
          // w przeglądarce dostawał 401 na każdym żądaniu JSON.
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${conn.token}`,
            ...(request.headers ?? {})
          },
          signal: AbortSignal.timeout(request.timeoutMs ?? 30_000)
        })
        const text = await response.text()
        let data: unknown = null
        try { data = text ? JSON.parse(text) : null } catch { data = text }
        return { ok: response.ok, status: response.status, data }
      } catch (reason) {
        return { ok: false, status: 0, error: String((reason as Error).message || reason) }
      }
    },
    onCoreStatus: () => () => undefined,
    selectFolder: () => Promise.resolve(null),
    openPath: () => Promise.resolve(''),
    listReferenceLibrary: () => Promise.resolve([]),
    importReferenceLibrary: () => Promise.resolve([]),
    getReferenceDataUri: () =>
      Promise.reject(new Error('Reference library is unavailable in browser preview.')),
    deleteReferenceImage: () => Promise.resolve(false)
  }
}
