// Faza-G/TOP5: budowanie srcdoc artefaktów (HTML/SVG) — osadzenie kodu + wstrzyknięcie CSP
// (blokada sieci) + skrypt auto-resize + wrap SVG. (Render w iframe weryfikuje user.)
import { describe, it, expect } from 'vitest'
import { isArtifactLang, buildArtifactSrcDoc, ARTIFACT_LANGS } from '../src/renderer/src/lib/artifacts'

describe('TOP5 — isArtifactLang', () => {
  it('rozpoznaje html/svg, odrzuca resztę (mermaid odłożony)', () => {
    expect(isArtifactLang('html')).toBe(true)
    expect(isArtifactLang('svg')).toBe(true)
    expect(isArtifactLang('python')).toBe(false)
    expect(isArtifactLang('mermaid')).toBe(false)
    expect(ARTIFACT_LANGS).toEqual(['html', 'svg'])
  })
})

describe('TOP5 — buildArtifactSrcDoc (html)', () => {
  it('osadza kod, wstrzykuje CSP (blokada sieci) i skrypt resize', () => {
    const s = buildArtifactSrcDoc('html', '<head></head><body><h1>Hi</h1></body>')
    expect(s).toContain('<h1>Hi</h1>')
    expect(s).toContain('Content-Security-Policy')
    expect(s).toContain("default-src 'none'") // brak connect/frame/object → brak egzfiltracji
    expect(s).toContain('__caeloArtifactHeight') // skrypt auto-resize
  })

  it('wstrzykuje CSP nawet dla gołego fragmentu (bez <head>)', () => {
    const s = buildArtifactSrcDoc('html', '<p>frag</p>')
    expect(s).toContain('<p>frag</p>')
    expect(s).toContain('Content-Security-Policy')
    expect(s).toContain('__caeloArtifactHeight')
  })

  it('nie pozwala na skrypty zewnętrzne (script-src tylko unsafe-inline)', () => {
    const s = buildArtifactSrcDoc('html', '<body></body>')
    expect(s).toContain("script-src 'unsafe-inline'")
    expect(s).not.toContain('http://')
    expect(s).not.toMatch(/script-src[^;]*https:/)
  })
})

describe('TOP5 — buildArtifactSrcDoc (svg)', () => {
  it('owija SVG w dokument z CSP', () => {
    const s = buildArtifactSrcDoc('svg', '<svg><circle r="5"/></svg>')
    expect(s).toContain('<svg><circle r="5"/></svg>')
    expect(s).toContain('<!doctype html>')
    expect(s).toContain('Content-Security-Policy')
  })
})
