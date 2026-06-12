// Wspólny cache stanu serwera (P2-2). `/models` i `/settings` były pobierane
// niezależnie w 6 modułach (ChatView/CodeView/Image/Video/Voice/Settings) — przy
// przełączaniu modułów (każdy remount = nowy GET) to się mnożyło. Tu trzymamy je
// RAZ per połączenie (baseUrl+token): deduplikacja zapytań w locie, współdzielony
// wynik między modułami i write-through przy zapisie ustawień, by kolejny montaż
// widział świeże dane bez ponownego GET-a. Bez nowej zależności (react-query/zustand
// świadomie nieużywane) — mały store + subskrypcja przez useState/useEffect.

import { useEffect, useState } from 'react'
import {
  getAuthStatus,
  getModels,
  getSettings,
  putSettings,
  type AuthResp,
  type Conn,
  type ModelsResp,
  type SettingsPatch,
  type SettingsResp
} from './api'

function connKey(conn: Conn): string {
  return `${conn.baseUrl}|${conn.token}`
}

export interface Snapshot<T> {
  data: T | null
  error: string | null
  loading: boolean
}

interface Entry<T> {
  snapshot: Snapshot<T>
  promise: Promise<T> | null
  subscribers: Set<() => void>
}

function createResource<T>(fetcher: (conn: Conn) => Promise<T>) {
  const entries = new Map<string, Entry<T>>()
  const idle: Snapshot<T> = { data: null, error: null, loading: false }

  function entryFor(key: string): Entry<T> {
    let e = entries.get(key)
    if (!e) {
      e = { snapshot: idle, promise: null, subscribers: new Set() }
      entries.set(key, e)
    }
    return e
  }

  function emit(e: Entry<T>, snapshot: Snapshot<T>): void {
    e.snapshot = snapshot
    e.subscribers.forEach((fn) => fn())
  }

  function load(conn: Conn, force = false): Promise<T> {
    const e = entryFor(connKey(conn))
    if (!force && e.snapshot.data !== null) return Promise.resolve(e.snapshot.data)
    if (e.promise) return e.promise // dedup: jedno zapytanie w locie
    emit(e, { data: e.snapshot.data, error: null, loading: true })
    const p = fetcher(conn)
      .then((data) => {
        e.promise = null
        emit(e, { data, error: null, loading: false })
        return data
      })
      .catch((err) => {
        e.promise = null
        emit(e, {
          data: e.snapshot.data,
          error: String((err as Error)?.message || err),
          loading: false
        })
        throw err
      })
    e.promise = p
    return p
  }

  /** Nadpisuje wartość w cache (write-through po zapisie) i budzi subskrybentów. */
  function write(conn: Conn, data: T): void {
    emit(entryFor(connKey(conn)), { data, error: null, loading: false })
  }

  function peek(conn: Conn): T | null {
    return entries.get(connKey(conn))?.snapshot.data ?? null
  }

  function useResource(conn: Conn): Snapshot<T> {
    const key = connKey(conn)
    // Lazy init: jeśli inny moduł już pobrał dane, pokaż je bez migotania.
    const [snap, setSnap] = useState<Snapshot<T>>(() => entryFor(key).snapshot)
    useEffect(() => {
      const e = entryFor(key)
      const update = (): void => setSnap(e.snapshot)
      e.subscribers.add(update)
      update() // domknij wyścig render→effect (snapshot mógł się zmienić)
      // Pobierz, gdy brak danych i nic nie leci. Błąd NIE jest cache'owany na
      // stałe — kolejny montaż modułu ponowi próbę (jak wcześniej per-komponent),
      // ale udany wynik jest współdzielony (dedup na ścieżce sukcesu).
      if (e.snapshot.data === null && e.promise === null) {
        void load(conn).catch(() => undefined)
      }
      return () => {
        e.subscribers.delete(update)
      }
      // conn zakodowany w `key` (baseUrl+token) — wystarczy reagować na key.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key])
    return snap
  }

  return { load, write, peek, useResource }
}

const modelsResource = createResource(getModels)
const settingsResource = createResource(getSettings)
const authResource = createResource(getAuthStatus)

/** Współdzielony, cache'owany odczyt `/auth/status` — używany przez footer App
 *  (wskaźnik źródła) i ekran Settings, by oba widziały TEN SAM stan auth. */
export function useAuthStatus(conn: Conn): {
  auth: AuthResp | null
  error: string | null
  loading: boolean
} {
  const s = authResource.useResource(conn)
  return { auth: s.data, error: s.error, loading: s.loading }
}

/** Wymusza ponowny odczyt `/auth/status` (po logowaniu/wylogowaniu/zapisie/usunięciu
 *  klucza lub zmianie źródła) i budzi subskrybentów — footer i Settings odświeżają się. */
export async function refreshAuth(conn: Conn): Promise<void> {
  await authResource.load(conn, true).catch(() => undefined)
}

/** Współdzielony, cache'owany odczyt `/models` (jeden GET na połączenie). */
export function useModels(conn: Conn): {
  models: ModelsResp | null
  error: string | null
  loading: boolean
} {
  const s = modelsResource.useResource(conn)
  return { models: s.data, error: s.error, loading: s.loading }
}

/** Współdzielony, cache'owany odczyt `/settings`. */
export function useSettings(conn: Conn): {
  settings: SettingsResp | null
  error: string | null
  loading: boolean
} {
  const s = settingsResource.useResource(conn)
  return { settings: s.data, error: s.error, loading: s.loading }
}

/**
 * Zapisuje ustawienia (PUT /settings) i aktualizuje cache (write-through), żeby
 * kolejne montowania modułów widziały świeże wartości bez ponownego GET-a. API key
 * nigdy nie wraca z serwera — odzwierciedlamy tylko `has_api_key`. Zwraca/propaguje
 * błąd jak `putSettings` (wołający pokazuje realny wynik — por. P1-6).
 */
/**
 * S35-a: scal `patch` w cache write-through dla KAŻDEGO pola odpowiedzi (nie tylko 4
 * wcześniej obsługiwanych) — wcześniej zapis `chat_effort`/`chat_search_mode`/`voice`…
 * nie trafiał do cache i cofał się w UI po remount. Iterujemy po kluczach odpowiedzi:
 * `api_key`/`auth_source` nie są polami `SettingsResp` (api_key tylko przełącza
 * `has_api_key`), więc się nie skopiują. Czysta funkcja — testowalna bez sieci.
 */
export function mergeSettings(current: SettingsResp, patch: SettingsPatch): SettingsResp {
  const next = { ...current } as Record<string, unknown>
  const p = patch as Record<string, unknown>
  for (const k of Object.keys(current)) {
    if (p[k] !== undefined) next[k] = p[k]
  }
  if (patch.api_key) next.has_api_key = true
  return next as unknown as SettingsResp
}

export async function saveSettings(conn: Conn, patch: SettingsPatch): Promise<{ ok: boolean }> {
  const res = await putSettings(conn, patch)
  const current = settingsResource.peek(conn)
  if (current) settingsResource.write(conn, mergeSettings(current, patch))
  return res
}
