import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { SecretVault, type SecretCipher } from '../src/main/secrets'

class TestCipher implements SecretCipher {
  constructor(private readonly available = true) {}
  isEncryptionAvailable(): boolean { return this.available }
  encryptString(value: string): Buffer { return Buffer.from(`encrypted:${value}`, 'utf8') }
  decryptString(value: Buffer): string {
    const text = value.toString('utf8')
    if (!text.startsWith('encrypted:')) throw new Error('bad ciphertext')
    return text.slice('encrypted:'.length)
  }
}

describe('SecretVault', () => {
  it('migrates plaintext only after persisting an encrypted vault', () => {
    const dir = mkdtempSync(join(tmpdir(), 'caelo-vault-'))
    const settings = join(dir, 'caelo_settings.json')
    const auth = join(dir, 'caelo_auth.json')
    writeFileSync(settings, JSON.stringify({ api_key: 'x-secret', google_api_key: 'g-secret', theme: 'dark' }))
    writeFileSync(auth, JSON.stringify({ access_token: 'oauth-secret', account: { name: 'Ada' } }))

    const vault = new SecretVault(new TestCipher(), dir)
    vault.load()
    const result = vault.migratePlaintext(settings, auth)

    expect(result).toEqual({ migrated: true, settingsCleaned: true, authRemoved: true })
    expect(readFileSync(vault.path, 'utf8')).not.toContain('x-secret')
    expect(JSON.parse(readFileSync(settings, 'utf8'))).toEqual({ theme: 'dark' })
    const reloaded = new SecretVault(new TestCipher(), dir)
    expect(reloaded.load()).toMatchObject({
      xai_api_key: 'x-secret', google_api_key: 'g-secret',
      oauth_tokens: { access_token: 'oauth-secret', account: { name: 'Ada' } }
    })
  })

  it('does not clean plaintext when OS encryption is unavailable', () => {
    const dir = mkdtempSync(join(tmpdir(), 'caelo-vault-'))
    const settings = join(dir, 'caelo_settings.json')
    writeFileSync(settings, JSON.stringify({ api_key: 'must-survive' }))
    const vault = new SecretVault(new TestCipher(false), dir)
    vault.load()
    expect(() => vault.migratePlaintext(settings, join(dir, 'caelo_auth.json'))).toThrow(
      'Operating-system secret encryption is unavailable'
    )
    expect(JSON.parse(readFileSync(settings, 'utf8')).api_key).toBe('must-survive')
  })

  it('keeps the newer vault value during an idempotent repeated migration', () => {
    const dir = mkdtempSync(join(tmpdir(), 'caelo-vault-'))
    const settings = join(dir, 'caelo_settings.json')
    const vault = new SecretVault(new TestCipher(), dir)
    vault.load()
    vault.patch({ xai_api_key: 'new-value' })
    writeFileSync(settings, JSON.stringify({ api_key: 'stale-value' }))
    vault.migratePlaintext(settings, join(dir, 'caelo_auth.json'))
    expect(vault.getSnapshot().xai_api_key).toBe('new-value')
  })

  it('upgrades a version 1 encrypted vault and preserves its secrets', () => {
    const dir = mkdtempSync(join(tmpdir(), 'caelo-vault-'))
    const cipher = new TestCipher()
    const vault = new SecretVault(cipher, dir)
    const old = {
      version: 1, revision: 4, xai_api_key: 'x-old', google_api_key: 'g-old',
      oauth_tokens: { access_token: 'a-old' }
    }
    const encrypted = cipher.encryptString(JSON.stringify(old)).toString('base64')
    writeFileSync(vault.path, JSON.stringify({ version: 1, encrypted }))

    expect(vault.load()).toMatchObject({
      version: 2, revision: 4, xai_api_key: 'x-old', google_api_key: 'g-old',
      openai_api_key: ''
    })
    expect(JSON.parse(readFileSync(vault.path, 'utf8')).version).toBe(2)
  })
})
