import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { spawn, execFileSync, ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'

// Linia handshake wypisywana przez sidecara (patrz grok_core/__main__.py).
const HANDSHAKE_PREFIX = '__GROK_CORE_READY__'

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

/** Wybór interpretera Pythona dla sidecara w trybie dev. */
function resolvePython(): string {
  if (process.env.GROK_CORE_PYTHON) return process.env.GROK_CORE_PYTHON
  const venvPy =
    process.platform === 'win32'
      ? join(repoRoot(), 'grok_core', '.venv', 'Scripts', 'python.exe')
      : join(repoRoot(), 'grok_core', '.venv', 'bin', 'python')
  if (existsSync(venvPy)) return venvPy
  return process.platform === 'win32' ? 'python' : 'python3'
}

/**
 * Jak uruchomić sidecar:
 *  - spakowany (.exe): bundlowany binarka PyInstaller z resources/grok-core,
 *  - dev: `python -m grok_core` z venv backendu.
 */
function resolveSidecar(): { command: string; args: string[]; cwd: string } {
  if (app.isPackaged) {
    const exeName = process.platform === 'win32' ? 'grok-core.exe' : 'grok-core'
    const dir = join(process.resourcesPath, 'grok-core')
    return { command: join(dir, exeName), args: [], cwd: dir }
  }
  return { command: resolvePython(), args: ['-m', 'grok_core'], cwd: repoRoot() }
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
  console.error(`[grok-core] ${reason}; restarting sidecar`)
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
        headers: { Authorization: `Bearer ${connection.token}` }
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

/** Uruchamia backend (dev: python -m grok_core; prod: grok-core.exe) i czeka na handshake. */
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
      GROK_CORE_TOKEN: token,
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
        }
      } else if (line) {
        console.log('[grok-core]', line)
      }
    })
  }

  coreProcess.stderr?.on('data', (chunk: Buffer) => {
    console.error('[grok-core:stderr]', chunk.toString().trimEnd())
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
    fetch(`${connection.baseUrl}/health`)
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
    title: 'Grok Desktop',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
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
  if (rendererUrl) {
    void mainWindow.loadURL(rendererUrl)
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

app.whenReady().then(() => {
  if (process.platform === 'win32') app.setAppUserModelId('com.grok.desktop')
  startCore()
  createWindow()

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
