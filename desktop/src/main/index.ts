import { app, BrowserWindow, dialog, ipcMain, Menu, shell } from 'electron'
import { spawn, execFileSync, ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'

// Linia handshake wypisywana przez sidecara (patrz caelo_core/__main__.py).
const HANDSHAKE_PREFIX = '__CAELO_CORE_READY__'

// Nadzór sidecara: po nagłym padzie restartujemy z narastającym backoffem.
const MAX_RESTARTS = 5
const HEALTH_INTERVAL_MS = 10_000
const HEALTH_FAILS_BEFORE_KILL = 3
const HANDSHAKE_TIMEOUT_MS = 30_000 // brak handshake w tym czasie -> kill + restart
const STABLE_MS = 30_000 // po tylu ms zdrowia 'ready' zerujemy licznik restartów (anty-storm)

export interface CoreConnection {
  status: 'starting' | 'ready' | 'error' | 'stopped'
  baseUrl?: string
  token?: string
  port?: number
  version?: string
  error?: string
}

let coreProcess: ChildProcess | null = null
let connection: CoreConnection = { status: 'starting' }
let mainWindow: BrowserWindow | null = null

let manualStop = false // true gdy zatrzymujemy sidecar celowo (quit) — nie restartuj
let restarts = 0 // kolejne restarty po padzie (reset po udanym /whoami)
let healthTimer: ReturnType<typeof setInterval> | null = null
let healthFails = 0
let handshakeTimer: ReturnType<typeof setTimeout> | null = null
let stableTimer: ReturnType<typeof setTimeout> | null = null

/** Katalog główny repo (monorepo) — w dev main jest w desktop/out/main. */
function repoRoot(): string {
  return resolve(__dirname, '..', '..', '..')
}

/** Ikona okna/paska zadań. W spakowanej aplikacji ikonę nosi sam plik .exe/.app
 *  (electron-builder z build/icon.*), więc liczy się głównie w dev oraz na Linuksie.
 *  build/ nie trafia do paczki — zwróć ścieżkę tylko, gdy plik istnieje. */
function windowIcon(): string | undefined {
  const png = join(__dirname, '..', '..', 'build', 'icon.png') // desktop/out/main -> desktop/build
  return existsSync(png) ? png : undefined
}

/** Wybór interpretera Pythona dla sidecara w trybie dev. */
function resolvePython(): string {
  if (process.env.CAELO_CORE_PYTHON) return process.env.CAELO_CORE_PYTHON
  const venvPy =
    process.platform === 'win32'
      ? join(repoRoot(), 'caelo_core', '.venv', 'Scripts', 'python.exe')
      : join(repoRoot(), 'caelo_core', '.venv', 'bin', 'python')
  if (existsSync(venvPy)) return venvPy
  return process.platform === 'win32' ? 'python' : 'python3'
}

/**
 * Jak uruchomić sidecar:
 *  - spakowany (.exe): bundlowany binarka PyInstaller z resources/caelo-core,
 *  - dev: `python -m caelo_core` z venv backendu.
 */
function resolveSidecar(): { command: string; args: string[]; cwd: string } {
  if (app.isPackaged) {
    const exeName = process.platform === 'win32' ? 'caelo-core.exe' : 'caelo-core'
    const dir = join(process.resourcesPath, 'caelo-core')
    return { command: join(dir, exeName), args: [], cwd: dir }
  }
  return { command: resolvePython(), args: ['-m', 'caelo_core'], cwd: repoRoot() }
}

function broadcast(): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('core:status', connection)
  }
}

/** Ubija proces I jego drzewo potomków (agent `run_command` spawnuje wnuki).
 *  Windows: `taskkill /T /F`; POSIX: SIGTERM + SIGKILL (fallback). `sync=true`
 *  (na quit) blokuje do zabicia, by nie zostawić osieroconych procesów. */
function treeKill(proc: ChildProcess, sync = false): void {
  const pid = proc.pid
  if (!pid) {
    try {
      proc.kill()
    } catch {
      /* noop */
    }
    return
  }
  if (process.platform === 'win32') {
    try {
      if (sync) {
        execFileSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
          windowsHide: true,
          timeout: 5000
        })
      } else {
        spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true })
      }
    } catch {
      try {
        proc.kill()
      } catch {
        /* noop */
      }
    }
  } else {
    try {
      proc.kill('SIGTERM')
    } catch {
      /* noop */
    }
    if (sync) {
      try {
        proc.kill('SIGKILL')
      } catch {
        /* noop */
      }
    } else {
      setTimeout(() => {
        try {
          proc.kill('SIGKILL')
        } catch {
          /* noop */
        }
      }, 2000)
    }
  }
}

function clearSupervisionTimers(): void {
  if (handshakeTimer) {
    clearTimeout(handshakeTimer)
    handshakeTimer = null
  }
  if (stableTimer) {
    clearTimeout(stableTimer)
    stableTimer = null
  }
}

/** Po STABLE_MS nieprzerwanego zdrowia zeruje licznik restartów. Anty-storm:
 *  proces musi się NAPRAWDĘ ustabilizować — sam udany handshake nie wystarcza,
 *  bo handshake-ok-ale-whoami-pada w pętli inaczej resetowałby budżet w nieskończoność. */
function scheduleStableReset(): void {
  if (stableTimer) clearTimeout(stableTimer)
  stableTimer = setTimeout(() => {
    restarts = 0
  }, STABLE_MS)
}

/** Ubija sidecar tak, by handler 'exit' przeprowadził restart (zamiast parkować w 'error'). */
function killCoreForRestart(reason: string): void {
  console.error(`[caelo-core] ${reason}; restarting sidecar`)
  if (coreProcess) treeKill(coreProcess)
}

/** Po handshake'u potwierdza token przez /whoami (z poziomu procesu głównego).
 *  Kilka prób (handshake już dowiódł, że serwer wstał); gdy mimo to /whoami pada,
 *  NIE parkujemy w 'error' — ubijamy proces, by zadziałała ścieżka restartu (P1-2). */
async function verifyConnection(): Promise<void> {
  if (!connection.baseUrl || !connection.token) return
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const res = await fetch(`${connection.baseUrl}/whoami`, {
        headers: { Authorization: `Bearer ${connection.token}` },
        signal: AbortSignal.timeout(5000) // P2-10: nie czekaj w nieskończoność na zawieszony socket
      })
      if (!res.ok) throw new Error(`/whoami -> HTTP ${res.status}`)
      connection = { ...connection, status: 'ready' }
      healthFails = 0
      startHealthMonitor()
      scheduleStableReset() // reset backoffu dopiero po N s zdrowia, nie natychmiast
      broadcast()
      return
    } catch (err) {
      if (attempt < 3) {
        await new Promise((r) => setTimeout(r, 500))
        continue
      }
      connection = { ...connection, status: 'error', error: `whoami failed: ${String(err)}` }
      broadcast()
      if (coreProcess && !manualStop) killCoreForRestart('whoami failed after handshake')
    }
  }
}

/** Uruchamia backend (dev: python -m caelo_core; prod: caelo-core.exe) i czeka na handshake. */
function startCore(): void {
  const { command, args, cwd } = resolveSidecar()
  const token = randomBytes(32).toString('hex')
  manualStop = false
  connection = { status: 'starting' }
  broadcast()

  coreProcess = spawn(command, args, {
    cwd,
    windowsHide: true, // sidecar ma konsolę (stdout=handshake) — ukryj jej okno
    env: {
      ...process.env,
      CAELO_CORE_TOKEN: token,
      // P3-4: wersja PRODUKTU (desktop/package.json) wstrzyknięta do sidecara, by
      // raportował ją w handshake/`/health` także w spakowanym buildzie (gdzie nie
      // może odczytać package.json). To JEDNO źródło prawdy dla wersji.
      CAELO_CORE_APP_VERSION: app.getVersion(),
      PYTHONUNBUFFERED: '1',
      PYTHONUTF8: '1'
    }
  })

  coreProcess.on('error', (err) => {
    connection = { status: 'error', error: `Failed to start sidecar (${command}): ${err.message}` }
    broadcast()
  })

  // Watchdog handshake (P1-2): jeśli sidecar nie wypisze linii handshake w czasie,
  // prawdopodobnie zawisł w 'starting' — ubij i pozwól ścieżce restartu zadziałać.
  handshakeTimer = setTimeout(() => {
    if (connection.status === 'starting' && coreProcess) {
      killCoreForRestart(`no handshake within ${HANDSHAKE_TIMEOUT_MS}ms`)
    }
  }, HANDSHAKE_TIMEOUT_MS)

  if (coreProcess.stdout) {
    const rl = createInterface({ input: coreProcess.stdout })
    rl.on('line', (raw) => {
      const line = raw.trim()
      if (line.startsWith(HANDSHAKE_PREFIX)) {
        try {
          const info = JSON.parse(line.slice(HANDSHAKE_PREFIX.length).trim())
          if (handshakeTimer) {
            clearTimeout(handshakeTimer) // handshake dotarł — wyłącz watchdog
            handshakeTimer = null
          }
          connection = {
            status: 'ready',
            port: info.port,
            token, // token z procesu głównego jest autorytatywny
            version: info.version,
            baseUrl: `http://127.0.0.1:${info.port}`
          }
          broadcast()
          void verifyConnection()
        } catch (err) {
          connection = { status: 'error', error: `Bad handshake: ${String(err)}` }
          broadcast()
          // S35-f: zepsuty handshake JSON parkował w 'error' z ŻYWYM sidecarem — watchdog
          // patrzy tylko na 'starting', więc nic go nie ubijało. Wyczyść watchdoga (i tak
          // już rozbrojony przez throw przed clearTimeout) i ubij, by ścieżka exit→restart
          // (backoff + MAX_RESTARTS) zadziałała, jak przy verifyConnection failure (powyżej).
          clearSupervisionTimers()
          if (coreProcess && !manualStop) killCoreForRestart(`bad handshake: ${String(err)}`)
        }
      } else if (line) {
        console.log('[caelo-core]', line)
      }
    })
  }

  coreProcess.stderr?.on('data', (chunk: Buffer) => {
    console.error('[caelo-core:stderr]', chunk.toString().trimEnd())
  })

  coreProcess.on('exit', (code, signal) => {
    coreProcess = null
    stopHealthMonitor()
    clearSupervisionTimers() // watchdog handshake + stable-reset należą do tego procesu
    if (manualStop) {
      connection = { ...connection, status: 'stopped' }
      broadcast()
      return
    }
    // Nagły pad — spróbuj wskrzesić sidecar z narastającym opóźnieniem.
    if (restarts < MAX_RESTARTS) {
      restarts += 1
      const delay = Math.min(restarts * 1000, 5000)
      connection = {
        status: 'starting',
        error: `Sidecar crashed (code=${code}, signal=${signal}); restart ${restarts}/${MAX_RESTARTS}…`
      }
      broadcast()
      setTimeout(() => {
        if (!manualStop) startCore()
      }, delay)
    } else {
      connection = {
        status: 'error',
        error: `Sidecar exited (code=${code}, signal=${signal}); exceeded ${MAX_RESTARTS} restarts`
      }
      broadcast()
    }
  })
}

function stopCore(): void {
  manualStop = true
  clearSupervisionTimers()
  stopHealthMonitor()
  if (coreProcess) {
    connection = { ...connection, status: 'stopped' }
    treeKill(coreProcess, true) // P1-2: synchroniczny tree-kill — zabij też wnuki (agent run_command)
    coreProcess = null
  }
}

/** Cykliczny health-check: 3 kolejne porażki /health -> ubij proces (wywoła restart). */
function startHealthMonitor(): void {
  stopHealthMonitor()
  healthTimer = setInterval(() => {
    if (!coreProcess || connection.status !== 'ready' || !connection.baseUrl) return
    // P2-10: timeout — sidecar żywy, ale nieodpowiadający nie może opóźniać detekcji
    // pada poza zamierzone ~30 s (3× interwał) do czasu TCP-timeoutu OS.
    fetch(`${connection.baseUrl}/health`, { signal: AbortSignal.timeout(5000) })
      .then((res) => {
        if (res.ok) {
          healthFails = 0
        } else {
          throw new Error(`HTTP ${res.status}`)
        }
      })
      .catch(() => {
        healthFails += 1
        if (healthFails >= HEALTH_FAILS_BEFORE_KILL && coreProcess) {
          healthFails = 0
          killCoreForRestart('health-check failed') // tree-kill; 'exit' zajmie się restartem
        }
      })
  }, HEALTH_INTERVAL_MS)
}

function stopHealthMonitor(): void {
  if (healthTimer) {
    clearInterval(healthTimer)
    healthTimer = null
  }
}

/** P1-1: do otwarcia na zewnątrz dopuszczamy tylko http(s) — nie `file:`,
 *  `javascript:`, własne protokoły itp. */
function isSafeExternalUrl(url: string): boolean {
  if (!url || typeof url !== 'string') return false
  try {
    const u = new URL(url)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

/** P1-1: `shell.openPath` jest do ścieżek systemu plików — odrzucamy URL-e
 *  (schemat://), niebezpieczne schematy i cele nieistniejące na dysku.
 *  (Litera dysku `C:\...` nie jest URL-em — wymaga `://` lub znanego schematu.) */
function isOpenablePath(target: string): boolean {
  if (!target || typeof target !== 'string') return false
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(target)) return false // dowolny schemat://
  if (/^(javascript|data|vbscript|file|about|chrome|blob):/i.test(target)) return false
  return existsSync(target) // musi być realną, istniejącą ścieżką
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    backgroundColor: '#0f1323',
    title: 'Caelo',
    icon: windowIcon(),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      // P2-14: sandbox=true — renderer w pełnym sandboksie Chromium. Preload jest
      // zgodny (używa WYŁĄCZNIE contextBridge/ipcRenderer + `import type`, który znika
      // przy kompilacji) — cała praca Node (spawn sidecara, dialog, shell.openPath)
      // dzieje się w procesie main przez IPC, nie w preloadzie. Razem z
      // contextIsolation + nodeIntegration:false = pełna izolacja renderera.
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  mainWindow.on('ready-to-show', () => mainWindow?.show())

  // Linki zewnętrzne otwieraj w domyślnej przeglądarce, nie w oknie aplikacji.
  // P1-1: tylko http(s) — inne schematy ignorujemy (nie przekazujemy do systemu).
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternalUrl(url)) void shell.openExternal(url)
    else console.warn('[main] blocked openExternal for non-http(s) URL:', url)
    return { action: 'deny' }
  })

  const rendererUrl = process.env['ELECTRON_RENDERER_URL']

  // P2-10: blokuj nawigację górnego poziomu poza renderer (np. drag&drop URL na okno,
  // przypadkowe window.location). SPA nawiguje stanem Reacta, więc realny 'will-navigate'
  // to anomalia — podmiana ramki aplikacji.
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const ok = rendererUrl ? url.startsWith(rendererUrl) : url.startsWith('file://')
    if (!ok) {
      event.preventDefault()
      console.warn('[main] blocked navigation to', url)
    }
  })

  // P2-10: ogranicz uprawnienia renderera do mikrofonu (Voice/dyktowanie) oraz
  // pełnego ekranu (przycisk fullscreen w odtwarzaczu wideo wymaga 'fullscreen' —
  // bez niego nic nie robi). Inne (geolokalizacja, powiadomienia, MIDI…) — odmowa
  // zamiast domyślnego auto-grantu dla treści na pętli zwrotnej.
  mainWindow.webContents.session.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(permission === 'media' || permission === 'fullscreen')
  })

  // Sprawdzanie pisowni: języki wg USTAWIEŃ SYSTEMU (np. polski na polskim Windowsie),
  // nie hardkodowany angielski. Czerwone podkreślenia pokazuje Chromium domyślnie; menu
  // z poprawkami budujemy w 'context-menu' poniżej. Słowniki Hunspell pobiera Electron
  // przy starcie — w sieci z TLS-interception pobranie może się nie udać (brak podkreśleń),
  // ale apka działa dalej (stąd try/catch). macOS używa NSSpellChecker (to no-op tam).
  try {
    const ses = mainWindow.webContents.session
    const available = new Set(ses.availableSpellCheckerLanguages)
    // Dopasuj kod języka systemu do dostępnych w spellcheckerze: dokładny ('en-US'),
    // bazowy ('pl-PL' → 'pl'), albo dowolny regionalny wariant tej samej bazy.
    const resolve = (pref: string): string | null => {
      if (available.has(pref)) return pref
      const base = pref.split('-')[0]
      if (available.has(base)) return base
      for (const a of available) if (a.split('-')[0] === base) return a
      return null
    }
    // Zachowaj kolejność preferencji systemu, bez duplikatów, cap 3 (mniej pobierań).
    const langs: string[] = []
    for (const pref of app.getPreferredSystemLanguages()) {
      const r = resolve(pref)
      if (r && !langs.includes(r)) langs.push(r)
      if (langs.length >= 3) break
    }
    // Fallback, gdy żaden język systemu nie ma słownika — angielski (jeśli dostępny).
    if (!langs.length) {
      const en = resolve('en-US')
      if (en) langs.push(en)
    }
    if (langs.length) ses.setSpellCheckerLanguages(langs)
  } catch (err) {
    console.warn('[main] spellchecker setup failed:', err)
  }

  // Menu kontekstowe (prawy klik): poprawki pisowni + standardowa edycja (jak w
  // Claude Code). Bez tego podkreślone błędy nie dają się poprawić kliknięciem.
  mainWindow.webContents.on('context-menu', (_event, params) => {
    const template: Electron.MenuItemConstructorOptions[] = []
    const wc = mainWindow?.webContents
    if (!wc) return

    // Sugestie pisowni dla podkreślonego słowa (tylko w polach edytowalnych).
    if (params.isEditable && params.misspelledWord) {
      for (const suggestion of params.dictionarySuggestions.slice(0, 5)) {
        template.push({ label: suggestion, click: () => wc.replaceMisspelling(suggestion) })
      }
      if (params.dictionarySuggestions.length === 0) {
        template.push({ label: 'No suggestions', enabled: false })
      }
      template.push({ type: 'separator' })
      template.push({
        label: 'Add to dictionary',
        click: () => wc.session.addWordToSpellCheckerDictionary(params.misspelledWord)
      })
      template.push({ type: 'separator' })
    }

    // Standardowe akcje edycji — włączane wg editFlags bieżącego zaznaczenia/pola.
    const ef = params.editFlags
    if (params.isEditable) {
      template.push({ role: 'undo', enabled: ef.canUndo })
      template.push({ role: 'redo', enabled: ef.canRedo })
      template.push({ type: 'separator' })
      template.push({ role: 'cut', enabled: ef.canCut })
      template.push({ role: 'copy', enabled: ef.canCopy })
      template.push({ role: 'paste', enabled: ef.canPaste })
      template.push({ type: 'separator' })
      template.push({ role: 'selectAll' })
    } else if (params.selectionText) {
      // Prawy klik na zaznaczonym tekście poza polem (np. transkrypt) → Kopiuj.
      template.push({ role: 'copy', enabled: ef.canCopy })
      template.push({ role: 'selectAll' })
    }

    if (template.length === 0) return
    Menu.buildFromTemplate(template).popup({ window: mainWindow ?? undefined })
  })

  if (rendererUrl) {
    void mainWindow.loadURL(rendererUrl)
    // DEV: aplikacja usuwa menu (Menu.setApplicationMenu(null)), więc domyślny skrót
    // Ctrl+Shift+I/F12 do DevTools nie działa. W trybie dev (rendererUrl ustawiony przez
    // electron-vite) przywróć F12 jako toggle — potrzebne m.in. do inspekcji ramek WS
    // (głos/STT-stream). W buildzie spakowanym (else) DevTools pozostają niedostępne.
    mainWindow.webContents.on('before-input-event', (_e, input) => {
      if (input.type === 'keyDown' && (input.key === 'F12'
          || (input.control && input.shift && input.key.toLowerCase() === 'i'))) {
        mainWindow?.webContents.toggleDevTools()
      }
    })
  } else {
    void mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

ipcMain.handle('core:get', () => connection)

// Natywny wybór folderu (np. folder wyjściowy mediów w Settings).
ipcMain.handle('dialog:selectFolder', async () => {
  const options = { properties: ['openDirectory'] as Array<'openDirectory'> }
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, options)
    : await dialog.showOpenDialog(options)
  return result.canceled || result.filePaths.length === 0 ? null : result.filePaths[0]
})

// Otwarcie pliku/folderu w domyślnej aplikacji systemu.
// P1-1: tylko realne ścieżki FS (nie URL-e/schematy) — inaczej blokujemy.
ipcMain.handle('shell:openPath', async (_event, target: string) => {
  if (!target) return 'no path'
  if (!isOpenablePath(target)) {
    console.warn('[main] blocked openPath for non-filesystem target:', target)
    return 'blocked: not a valid filesystem path'
  }
  return shell.openPath(target)
})

/** M15-8: auto-aktualizacja przez electron-updater + GitHub Releases (najpierw Windows).
 *  `electron-updater` to OPCJONALNA zależność runtime — ładujemy ją przez `require`
 *  w try/catch, więc brak pakietu (przed `npm install electron-updater`) nie wywraca
 *  apki ani typechecku, a w spakowanym buildzie auto-update po prostu „ożywa".
 *  Działa tylko w buildzie (`app.isPackaged`); wyłączysz przez CAELO_DISABLE_AUTOUPDATE=1. */
function initAutoUpdate(): void {
  if (!app.isPackaged) return // dev nie ma feeda wydań
  if (process.env.CAELO_DISABLE_AUTOUPDATE === '1') {
    console.log('[update] disabled via CAELO_DISABLE_AUTOUPDATE')
    return
  }
  let autoUpdater: {
    autoDownload: boolean
    on: (ev: string, cb: (arg?: unknown) => void) => void
    checkForUpdates: () => Promise<unknown>
    quitAndInstall: () => void
  } | null = null
  try {
    // require (nie import) — bez statycznego rozwiązywania modułu: typecheck przechodzi
    // nawet gdy pakiet nie jest jeszcze zainstalowany.
    autoUpdater = require('electron-updater').autoUpdater
  } catch {
    console.warn('[update] electron-updater not installed — auto-update disabled')
    return
  }
  if (!autoUpdater) return
  try {
    autoUpdater.autoDownload = true
    autoUpdater.on('update-available', (info) =>
      console.log('[update] available:', (info as { version?: string } | undefined)?.version)
    )
    autoUpdater.on('update-not-available', () => console.log('[update] up to date'))
    autoUpdater.on('error', (err) => console.error('[update] error:', err))
    autoUpdater.on('update-downloaded', (info) => {
      const version = (info as { version?: string } | undefined)?.version ?? ''
      console.log('[update] downloaded:', version)
      if (!mainWindow || mainWindow.isDestroyed()) return
      void dialog
        .showMessageBox(mainWindow, {
          type: 'info',
          buttons: ['Restart now', 'Later'],
          defaultId: 0,
          cancelId: 1,
          title: 'Update ready',
          message: `Caelo ${version} has been downloaded.`,
          detail: 'Restart the app to apply the update.'
        })
        .then((r) => {
          if (r.response === 0) autoUpdater?.quitAndInstall()
        })
    })
    void autoUpdater.checkForUpdates()
  } catch (err) {
    console.error('[update] init failed:', err)
  }
}

app.whenReady().then(() => {
  if (process.platform === 'win32') app.setAppUserModelId('com.caelo.desktop')
  // Usuń pasek menu aplikacji (File/Edit/View/Window) na Windows/Linux — niepotrzebny
  // (nawigacja jest w UI). Skróty edycji w polach tekstowych działają i bez menu
  // (obsługuje je Chromium). Na macOS zostawiamy domyślne menu systemowe, bo jego
  // brak łamie standardowe skróty (Cmd+Q, kopiuj/wklej w menu aplikacji).
  if (process.platform !== 'darwin') Menu.setApplicationMenu(null)
  startCore()
  createWindow()
  initAutoUpdate() // M15-8: sprawdź aktualizacje (no-op w dev / bez electron-updater)

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  manualStop = true // zamykamy aplikację — nie restartuj sidecara, jeśli teraz padnie
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('quit', stopCore)
