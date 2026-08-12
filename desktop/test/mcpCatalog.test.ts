// Faza-G/TOP4: katalog MCP — podstawianie inputów wpisu w McpServerInput + walidacja wymaganych.
import { describe, it, expect } from 'vitest'
import {
  missingRequired,
  resolveCatalogEntry,
  commandPreview
} from '../src/renderer/src/lib/mcpCatalog'
import type { McpCatalogEntry } from '../src/renderer/src/lib/api'

const FS: McpCatalogEntry = {
  id: 'filesystem',
  name: 'Filesystem',
  description: 'd',
  category: 'Files',
  transport: 'stdio',
  command: ['npx', '-y', '@modelcontextprotocol/server-filesystem', '{path}'],
  inputs: [{ key: 'path', label: 'Dir', target: 'arg', required: true }]
}

const GH: McpCatalogEntry = {
  id: 'github',
  name: 'GitHub',
  description: 'd',
  category: 'Development',
  transport: 'stdio',
  command: ['npx', '-y', '@modelcontextprotocol/server-github'],
  inputs: [
    { key: 'token', label: 'Token', target: 'env', env_key: 'GITHUB_PERSONAL_ACCESS_TOKEN', required: true, secret: true }
  ]
}

describe('TOP4 — resolveCatalogEntry', () => {
  it('podstawia arg w command i ustawia enabled=false (install != autostart)', () => {
    const out = resolveCatalogEntry(FS, { path: 'C:/work' })
    expect(out.command).toEqual(['npx', '-y', '@modelcontextprotocol/server-filesystem', 'C:/work'])
    expect(out.enabled).toBe(false)
    expect(out.id).toBe('filesystem')
  })

  it('mapuje input env na env_key (klucz, nie nazwa pola)', () => {
    const out = resolveCatalogEntry(GH, { token: 'ghp_x' })
    expect(out.env).toEqual({ GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_x' })
    expect(out.command).toEqual(['npx', '-y', '@modelcontextprotocol/server-github'])
  })

  it('puste/brakujące wartości nie podstawiają (token placeholder zostaje)', () => {
    const out = resolveCatalogEntry(FS, {})
    expect(out.command).toContain('{path}')
    expect(out.env).toBeUndefined()
  })
})

describe('TOP4 — missingRequired', () => {
  it('zwraca puste wymagane pola', () => {
    expect(missingRequired(FS, {})).toEqual(['path'])
    expect(missingRequired(FS, { path: '  ' })).toEqual(['path']) // same białe znaki = brak
    expect(missingRequired(FS, { path: 'x' })).toEqual([])
  })
})

describe('TOP4 — commandPreview', () => {
  it('pokazuje komendę z podstawionym argiem, bez wartości env (sekretów)', () => {
    expect(commandPreview(GH, { token: 'ghp_secret' })).toBe(
      'npx -y @modelcontextprotocol/server-github'
    )
    expect(commandPreview(FS, { path: '/tmp' })).toBe(
      'npx -y @modelcontextprotocol/server-filesystem /tmp'
    )
  })
})

// 28c/28d: transport `http` (lokalny serwer MCP wołany przez nas) + input `auth`.
const PLUGIN: McpCatalogEntry = {
  id: 'sceneagent-mcp-plugin',
  name: 'SceneAgent MCP (Plugin Edition)',
  description: 'd',
  category: '3D',
  transport: 'http',
  url: 'http://127.0.0.1:8772/mcp',
  inputs: [{ key: 'token', label: 'Access token', target: 'auth', required: true, secret: true }]
}

describe('28c/28d — http w katalogu', () => {
  it('input auth składa nagłówek Bearer i nie rusza command', () => {
    const out = resolveCatalogEntry(PLUGIN, { token: 'abc123' })
    expect(out.transport).toBe('http')
    expect(out.url).toBe('http://127.0.0.1:8772/mcp')
    expect(out.authorization).toBe('Bearer abc123')
    expect(out.command).toBeUndefined()
    expect(out.enabled).toBe(false)
  })

  it('nie dubluje prefiksu, gdy user wkleił go razem z tokenem', () => {
    expect(resolveCatalogEntry(PLUGIN, { token: 'Bearer abc123' }).authorization).toBe(
      'Bearer abc123'
    )
    expect(resolveCatalogEntry(PLUGIN, { token: 'bearer abc123' }).authorization).toBe(
      'bearer abc123'
    )
  })

  it('bez tokenu nie wysyła pustego nagłówka', () => {
    expect(resolveCatalogEntry(PLUGIN, {}).authorization).toBeUndefined()
    expect(missingRequired(PLUGIN, {})).toEqual(['token'])
  })

  it('podgląd pokazuje adres, NIGDY tokenu — consent dotyczy tego, co wywołamy', () => {
    const preview = commandPreview(PLUGIN, { token: 'super-secret' })
    expect(preview).toBe('http://127.0.0.1:8772/mcp')
    expect(preview).not.toContain('super-secret')
  })
})
