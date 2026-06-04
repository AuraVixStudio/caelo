import { contextBridge, ipcRenderer } from 'electron'
import type { CoreConnection } from '../main/index'

// Bezpieczny most: renderer dostaje wyłącznie te metody (contextIsolation).
const grokApi = {
  /** Bieżący stan połączenia z backendem (port, token, baseUrl). */
  getCore: (): Promise<CoreConnection> => ipcRenderer.invoke('core:get'),

  /** Subskrypcja zmian stanu połączenia. Zwraca funkcję wypisującą. */
  onCoreStatus: (callback: (status: CoreConnection) => void): (() => void) => {
    const listener = (_event: unknown, status: CoreConnection): void => callback(status)
    ipcRenderer.on('core:status', listener)
    return () => ipcRenderer.removeListener('core:status', listener)
  },

  /** Natywny wybór folderu (zwraca ścieżkę lub null po anulowaniu). */
  selectFolder: (): Promise<string | null> => ipcRenderer.invoke('dialog:selectFolder'),

  /** Otwiera plik/folder w domyślnej aplikacji systemu. */
  openPath: (path: string): Promise<string> => ipcRenderer.invoke('shell:openPath', path)
}

contextBridge.exposeInMainWorld('grok', grokApi)

export type GrokApi = typeof grokApi
