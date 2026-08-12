// Rozdzielczości wideo zależne od modelu: 1080p tylko na 1.5 (docs x.ai 2026-07).
import { describe, it, expect } from 'vitest'
import {
  IMAGE_MODELS,
  VIDEO_MAX_REFERENCE_IMAGES,
  VIDEO_RESOLUTIONS,
  imageModelSupportsQuality,
  videoModelSupportsReferences,
  videoResolutionsFor
} from '../src/renderer/src/lib/constants'

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

// Reference-to-video (docs x.ai 2026-08): do 3 obrazów, tylko model 1.5. Wysłanie ich
// do bazowego modelu = 400 na całym żądaniu, więc UI musi je chować.
describe('videoModelSupportsReferences', () => {
  it('1.5 przyjmuje obrazy referencyjne', () => {
    expect(videoModelSupportsReferences('grok-imagine-video-1.5')).toBe(true)
  })

  it('model bazowy i pusty ich nie przyjmują', () => {
    expect(videoModelSupportsReferences('grok-imagine-video')).toBe(false)
    expect(videoModelSupportsReferences('')).toBe(false)
  })

  it('limit to 3 (limit API)', () => {
    expect(VIDEO_MAX_REFERENCE_IMAGES).toBe(3)
  })
})

// `quality` (low|medium) dokumentowane WYŁĄCZNIE dla grok-imagine-image-2.0.
describe('imageModelSupportsQuality', () => {
  it('tylko 2.0 → true', () => {
    expect(imageModelSupportsQuality('grok-imagine-image-2.0')).toBe(true)
    expect(imageModelSupportsQuality('grok-imagine-image')).toBe(false)
    expect(imageModelSupportsQuality('grok-imagine-image-quality')).toBe(false)
    expect(imageModelSupportsQuality('')).toBe(false)
  })

  it('2.0 jest na liście zapasowej modeli obrazu', () => {
    expect(IMAGE_MODELS).toContain('grok-imagine-image-2.0')
  })
})
