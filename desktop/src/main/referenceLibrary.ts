import { app, BrowserWindow, dialog, net, protocol } from 'electron'
import { randomBytes } from 'node:crypto'
import { copyFile, mkdir, readFile, readdir, rm, stat } from 'node:fs/promises'
import { basename, extname, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const REFERENCE_SCHEME = 'caelo-reference'
const MAX_REFERENCE_BYTES = 64 * 1024 * 1024
const MIME_BY_EXTENSION: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.bmp': 'image/bmp',
  '.avif': 'image/avif'
}

export interface NativeReferenceItem {
  id: string
  name: string
  mime: string
  bytes: number
  updatedAt: number
  uri: string
}

/** Ten sam prosty folder, którego używa dotychczasowy backend. Biblioteka nie
 * zależy jednak od HTTP ani SQLite: Electron czyta i kopiuje pliki bezpośrednio. */
export function referenceLibraryRoot(): string {
  const localAppData = process.env.LOCALAPPDATA
  return localAppData
    ? join(localAppData, 'Caelo', 'reference_library')
    : join(app.getPath('userData'), 'reference_library')
}

function safeDisplayName(value: string): string {
  const cleaned = basename(value)
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned || 'reference-image'
}

function storedFileName(id: string, originalName: string): string {
  return `${id}__${safeDisplayName(originalName)}`
}

function parseStoredName(fileName: string): { id: string; name: string } | null {
  const native = /^([a-f0-9]{32})__(.+)$/i.exec(fileName)
  if (native) return { id: native[1].toLowerCase(), name: native[2] }
  const legacy = /^([a-f0-9]{32})\.[^.]+$/i.exec(fileName)
  if (legacy) return { id: legacy[1].toLowerCase(), name: fileName }
  return null
}

async function ensureRoot(): Promise<string> {
  const root = referenceLibraryRoot()
  await mkdir(root, { recursive: true })
  return root
}

async function resolveReferenceFile(id: string): Promise<string | null> {
  if (!/^[a-f0-9]{32}$/i.test(id)) return null
  const root = await ensureRoot()
  const entries = await readdir(root, { withFileTypes: true })
  const match = entries.find((entry) => entry.isFile() && entry.name.toLowerCase().startsWith(`${id.toLowerCase()}__`))
    ?? entries.find((entry) => entry.isFile() && entry.name.toLowerCase().startsWith(`${id.toLowerCase()}.`))
  return match ? join(root, match.name) : null
}

export async function listNativeReferences(): Promise<NativeReferenceItem[]> {
  const root = await ensureRoot()
  const entries = await readdir(root, { withFileTypes: true })
  const items = await Promise.all(entries.filter((entry) => entry.isFile()).map(async (entry) => {
    const extension = extname(entry.name).toLowerCase()
    const mime = MIME_BY_EXTENSION[extension]
    const parsed = parseStoredName(entry.name)
    if (!mime || !parsed) return null
    const info = await stat(join(root, entry.name))
    return {
      id: parsed.id,
      name: parsed.name,
      mime,
      bytes: info.size,
      updatedAt: info.mtimeMs,
      uri: `${REFERENCE_SCHEME}://image/${parsed.id}`
    } satisfies NativeReferenceItem
  }))
  return items
    .filter((item): item is NativeReferenceItem => item !== null)
    .sort((left, right) => right.updatedAt - left.updatedAt)
}

export async function importNativeReferences(window: BrowserWindow | null): Promise<NativeReferenceItem[]> {
  const options = {
    title: 'Import reference images',
    properties: ['openFile', 'multiSelections'] as Array<'openFile' | 'multiSelections'>,
    filters: [{ name: 'Images', extensions: Object.keys(MIME_BY_EXTENSION).map((ext) => ext.slice(1)) }]
  }
  const result = window
    ? await dialog.showOpenDialog(window, options)
    : await dialog.showOpenDialog(options)
  if (result.canceled || result.filePaths.length === 0) return []

  const root = await ensureRoot()
  const imported: NativeReferenceItem[] = []
  for (const source of result.filePaths) {
    const extension = extname(source).toLowerCase()
    const mime = MIME_BY_EXTENSION[extension]
    if (!mime) throw new Error(`Unsupported image format: ${basename(source)}`)
    const sourceInfo = await stat(source)
    if (!sourceInfo.isFile()) continue
    if (sourceInfo.size > MAX_REFERENCE_BYTES) {
      throw new Error(`${basename(source)} is larger than 64 MB.`)
    }
    const id = randomBytes(16).toString('hex')
    const name = safeDisplayName(basename(source))
    const destination = join(root, storedFileName(id, name))
    await copyFile(source, destination)
    const copiedInfo = await stat(destination)
    imported.push({
      id,
      name,
      mime,
      bytes: copiedInfo.size,
      updatedAt: copiedInfo.mtimeMs,
      uri: `${REFERENCE_SCHEME}://image/${id}`
    })
  }
  return imported
}

export async function getNativeReferenceDataUri(id: string): Promise<string> {
  const path = await resolveReferenceFile(id)
  if (!path) throw new Error('Reference image was not found in the library.')
  const mime = MIME_BY_EXTENSION[extname(path).toLowerCase()]
  if (!mime) throw new Error('Unsupported reference image format.')
  const data = await readFile(path)
  return `data:${mime};base64,${data.toString('base64')}`
}

/** Usuwa obraz z biblioteki. `resolveReferenceFile` waliduje id (32 hex) i zwraca
 * ścieżkę WYŁĄCZNIE z folderu biblioteki, więc kasowanie nie wyjdzie poza niego.
 * Nieznane id nie jest błędem — kafelek mógł już zniknąć w innym oknie. */
export async function deleteNativeReference(id: string): Promise<boolean> {
  const path = await resolveReferenceFile(id)
  if (!path) return false
  await rm(path, { force: true })
  return true
}

/** Strumieniowy podgląd obrazów z folderu biblioteki, bez kodowania base64 i API. */
export function registerReferenceLibraryProtocol(): void {
  protocol.handle(REFERENCE_SCHEME, async (request) => {
    try {
      const url = new URL(request.url)
      const id = url.pathname.replace(/^\//, '')
      if (url.hostname !== 'image') return new Response('Invalid reference URL', { status: 400 })
      const path = await resolveReferenceFile(id)
      if (!path) return new Response('Reference image not found', { status: 404 })
      return net.fetch(pathToFileURL(path).toString())
    } catch {
      return new Response('Reference image unavailable', { status: 502 })
    }
  })
}
