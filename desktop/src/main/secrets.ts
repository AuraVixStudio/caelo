import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync
} from 'node:fs'
import { dirname, join } from 'node:path'

export const SECRET_SCHEMA_VERSION = 2

export interface SecretSnapshot {
  version: 2
  revision: number
  xai_api_key: string
  google_api_key: string
  openai_api_key: string
  oauth_tokens: Record<string, unknown>
}

export interface SecretCipher {
  isEncryptionAvailable(): boolean
  encryptString(value: string): Buffer
  decryptString(value: Buffer): string
}

interface SecretEnvelope {
  version: 1 | 2
  encrypted: string
}

export interface SecretMigrationResult {
  migrated: boolean
  settingsCleaned: boolean
  authRemoved: boolean
}

const EMPTY: SecretSnapshot = {
  version: SECRET_SCHEMA_VERSION,
  revision: 0,
  xai_api_key: '',
  google_api_key: '',
  openai_api_key: '',
  oauth_tokens: {}
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function cleanSnapshot(value: unknown): SecretSnapshot {
  if (!isObject(value) || (value.version !== 1 && value.version !== SECRET_SCHEMA_VERSION)) {
    throw new Error('Unsupported secret vault format')
  }
  return {
    version: SECRET_SCHEMA_VERSION,
    revision: Number.isSafeInteger(value.revision) && Number(value.revision) >= 0
      ? Number(value.revision)
      : 0,
    xai_api_key: typeof value.xai_api_key === 'string' ? value.xai_api_key : '',
    google_api_key: typeof value.google_api_key === 'string' ? value.google_api_key : '',
    openai_api_key: typeof value.openai_api_key === 'string' ? value.openai_api_key : '',
    oauth_tokens: isObject(value.oauth_tokens) ? { ...value.oauth_tokens } : {}
  }
}

function readJsonObject(path: string): Record<string, unknown> | null {
  if (!existsSync(path)) return null
  const parsed: unknown = JSON.parse(readFileSync(path, 'utf8'))
  if (!isObject(parsed)) throw new Error(`Expected a JSON object in ${path}`)
  return parsed
}

function atomicWrite(path: string, data: string | Buffer): void {
  mkdirSync(dirname(path), { recursive: true })
  const temporary = `${path}.${process.pid}.${Date.now()}.tmp`
  writeFileSync(temporary, data, { mode: 0o600 })
  renameSync(temporary, path)
  try {
    chmodSync(path, 0o600)
  } catch {
    // Windows ACLs are governed by DPAPI/user profile; chmod is best-effort there.
  }
}

/**
 * Versioned OS-backed vault. The cipher is injected so file/migration behaviour can
 * be tested without loading Electron in Vitest.
 */
export class SecretVault {
  readonly path: string
  private snapshot: SecretSnapshot = { ...EMPTY, oauth_tokens: {} }

  constructor(
    private readonly cipher: SecretCipher,
    dataDir: string
  ) {
    this.path = join(dataDir, 'secrets.dat')
  }

  load(): SecretSnapshot {
    if (!existsSync(this.path)) {
      this.snapshot = { ...EMPTY, oauth_tokens: {} }
      return this.getSnapshot()
    }
    if (!this.cipher.isEncryptionAvailable()) {
      throw new Error('Operating-system secret encryption is unavailable')
    }
    const envelope: unknown = JSON.parse(readFileSync(this.path, 'utf8'))
    if (!isObject(envelope) || (envelope.version !== 1 && envelope.version !== SECRET_SCHEMA_VERSION) ||
        typeof envelope.encrypted !== 'string') {
      throw new Error('Invalid secret vault envelope')
    }
    const plain = this.cipher.decryptString(Buffer.from(envelope.encrypted, 'base64'))
    const decoded: unknown = JSON.parse(plain)
    this.snapshot = cleanSnapshot(decoded)
    if (envelope.version !== SECRET_SCHEMA_VERSION ||
        (isObject(decoded) && decoded.version !== SECRET_SCHEMA_VERSION)) {
      this.persist()
    }
    return this.getSnapshot()
  }

  getSnapshot(): SecretSnapshot {
    return { ...this.snapshot, oauth_tokens: { ...this.snapshot.oauth_tokens } }
  }

  replace(next: SecretSnapshot): SecretSnapshot {
    this.snapshot = cleanSnapshot(next)
    this.persist()
    return this.getSnapshot()
  }

  patch(patch: Partial<Pick<SecretSnapshot, 'xai_api_key' | 'google_api_key' | 'openai_api_key' | 'oauth_tokens'>>): SecretSnapshot {
    const next: SecretSnapshot = {
      ...this.snapshot,
      ...patch,
      oauth_tokens: patch.oauth_tokens
        ? { ...patch.oauth_tokens }
        : { ...this.snapshot.oauth_tokens },
      version: SECRET_SCHEMA_VERSION,
      revision: this.snapshot.revision + 1
    }
    return this.replace(next)
  }

  persist(): void {
    if (!this.cipher.isEncryptionAvailable()) {
      throw new Error('Operating-system secret encryption is unavailable')
    }
    const encrypted = this.cipher.encryptString(JSON.stringify(this.snapshot))
    const envelope: SecretEnvelope = {
      version: SECRET_SCHEMA_VERSION,
      encrypted: encrypted.toString('base64')
    }
    atomicWrite(this.path, JSON.stringify(envelope))
  }

  /**
   * One-time, crash-safe migration. The encrypted vault is persisted first. Only
   * then are secret fields removed from settings and the OAuth file deleted.
   * Existing vault values win, making repeated starts idempotent.
   */
  migratePlaintext(settingsPath: string, authPath: string): SecretMigrationResult {
    const settings = readJsonObject(settingsPath)
    const auth = readJsonObject(authPath)
    const xai = typeof settings?.api_key === 'string' ? settings.api_key.trim() : ''
    const google = typeof settings?.google_api_key === 'string' ? settings.google_api_key.trim() : ''
    const openai = typeof settings?.openai_api_key === 'string' ? settings.openai_api_key.trim() : ''
    const oauth = auth ?? {}
    const hasLegacy = Boolean(xai || google || openai || Object.keys(oauth).length)

    if (hasLegacy) {
      const changed = (!this.snapshot.xai_api_key && xai) ||
        (!this.snapshot.google_api_key && google) ||
        (!this.snapshot.openai_api_key && openai) ||
        (!Object.keys(this.snapshot.oauth_tokens).length && Object.keys(oauth).length)
      if (changed) {
        this.patch({
          xai_api_key: this.snapshot.xai_api_key || xai,
          google_api_key: this.snapshot.google_api_key || google,
          openai_api_key: this.snapshot.openai_api_key || openai,
          oauth_tokens: Object.keys(this.snapshot.oauth_tokens).length
            ? this.snapshot.oauth_tokens
            : oauth
        })
      } else if (!existsSync(this.path)) {
        this.persist()
      }
    }

    let settingsCleaned = false
    if (settings && ('api_key' in settings || 'google_api_key' in settings ||
        'openai_api_key' in settings)) {
      delete settings.api_key
      delete settings.google_api_key
      delete settings.openai_api_key
      atomicWrite(settingsPath, JSON.stringify(settings, null, 2))
      settingsCleaned = true
    }

    let authRemoved = false
    if (auth && existsSync(authPath)) {
      rmSync(authPath)
      authRemoved = true
    }
    return { migrated: hasLegacy, settingsCleaned, authRemoved }
  }
}
