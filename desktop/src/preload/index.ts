import { contextBridge, ipcRenderer } from 'electron'
import type { CoreConnection } from '../main/index'
import type { CoreRequestInput, CoreRequestResult } from '../main/coreRequest'
import type { NativeReferenceItem } from '../main/referenceLibrary'

// Bezpieczny most: renderer dostaje wyłącznie te metody (contextIsolation).
const caeloApi = {
  /** Bieżący stan połączenia z backendem (port, token, baseUrl). */
  getCore: (): Promise<CoreConnection> => ipcRenderer.invoke('core:get'),

  /** Uwierzytelnione żądanie JSON wykonywane w procesie głównym Electrona. */
  coreRequest: (request: CoreRequestInput): Promise<CoreRequestResult> =>
    ipcRenderer.invoke('core:request', request),

  /** Subskrypcja zmian stanu połączenia. Zwraca funkcję wypisującą. */
  onCoreStatus: (callback: (status: CoreConnection) => void): (() => void) => {
    const listener = (_event: unknown, status: CoreConnection): void => callback(status)
    ipcRenderer.on('core:status', listener)
    return () => ipcRenderer.removeListener('core:status', listener)
  },

  /** Natywny wybór folderu (zwraca ścieżkę lub null po anulowaniu). */
  selectFolder: (): Promise<string | null> => ipcRenderer.invoke('dialog:selectFolder'),

  /** Otwiera plik/folder w domyślnej aplikacji systemu. */
  openPath: (path: string): Promise<string> => ipcRenderer.invoke('shell:openPath', path),

  /** Plikowa biblioteka obrazów referencyjnych — bez połączenia z backendem. */
  listReferenceLibrary: (): Promise<NativeReferenceItem[]> => ipcRenderer.invoke('reference-library:list'),
  importReferenceLibrary: (): Promise<NativeReferenceItem[]> => ipcRenderer.invoke('reference-library:import'),
  getReferenceDataUri: (id: string): Promise<string> => ipcRenderer.invoke('reference-library:data-uri', id),
  deleteReferenceImage: (id: string): Promise<boolean> =>
    ipcRenderer.invoke('reference-library:delete', id)
}

contextBridge.exposeInMainWorld('caelo', caeloApi)

export type CaeloApi = typeof caeloApi
