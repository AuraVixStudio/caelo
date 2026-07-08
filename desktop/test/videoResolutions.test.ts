// Rozdzielczości wideo zależne od modelu: 1080p tylko na 1.5 (docs x.ai 2026-07).
import { describe, it, expect } from 'vitest'
import { VIDEO_RESOLUTIONS, videoResolutionsFor } from '../src/renderer/src/lib/constants'

describe('videoResolutionsFor', () => {
  it('1.5 model exposes 1080p', () => {
    expect(videoResolutionsFor('grok-imagine-video-1.5')).toEqual(['480p', '720p', '1080p'])
  })

  it('base model tops out at 720p (no 1080p)', () => {
    expect(videoResolutionsFor('grok-imagine-video')).toEqual(['480p', '720p'])
  })

  it('unknown/empty model falls back to base set', () => {
    expect(videoResolutionsFor('')).toEqual(['480p', '720p'])
  })

  it('full resolution list includes 1080p', () => {
    expect(VIDEO_RESOLUTIONS).toContain('1080p')
  })
})
