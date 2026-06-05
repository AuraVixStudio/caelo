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
    onCoreStatus: () => () => undefined,
    selectFolder: () => Promise.resolve(null),
    openPath: () => Promise.resolve('')
  }
}
