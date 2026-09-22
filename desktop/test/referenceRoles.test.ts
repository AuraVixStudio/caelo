import { describe, expect, it } from 'vitest'
import type { ModelCapabilities } from '../src/renderer/src/lib/api'
import {
  defaultReferenceRole,
  imageReferenceRoleOptions,
  normalizeReferenceRoles
} from '../src/renderer/src/lib/referenceRoles'

function capabilities(overrides: Partial<ModelCapabilities>): ModelCapabilities {
  return {
    operations: ['text2img', 'edit', 'variation'],
    input_modalities: ['text', 'image'],
    output_modalities: ['image'],
    aspect_ratios: [],
    resolutions: [],
    duration_min: null,
    duration_max: null,
    durations: [],
    supports_quality: false,
    quality_levels: [],
    max_reference_images: 14,
    max_character_reference_images: 0,
    max_object_reference_images: 0,
    max_style_reference_images: 0,
    supports_streaming: false,
    supports_tools: false,
    thinking: false,
    thinking_levels: [],
    search_grounding: false,
    multi_turn: false,
    native_audio: false,
    supports_seed: false,
    first_last_frame: false,
    video_extension: false,
    extension_seconds: null,
    extension_resolutions: [],
    edit_uploaded_video: false,
    supports_negative_prompt: false,
    notes: [],
    ...overrides
  }
}

describe('role zdjęć referencyjnych Google', () => {
  it('Nano Banana 2 udostępnia Character, General, Object i Starting Image bez Style', () => {
    const options = imageReferenceRoleOptions(capabilities({
      max_character_reference_images: 4,
      max_object_reference_images: 10
    }))

    expect(options.map((option) => option.value)).toEqual([
      'character', 'general', 'object', 'starting_image'
    ])
    expect(defaultReferenceRole(options)).toBe('general')
  })

  it('Nano Banana Pro udostępnia wszystkie pięć ról', () => {
    const options = imageReferenceRoleOptions(capabilities({
      max_character_reference_images: 5,
      max_object_reference_images: 6,
      max_style_reference_images: 3
    }))

    expect(options.map((option) => option.value)).toEqual([
      'character', 'general', 'object', 'style', 'starting_image'
    ])
  })

  it('po zmianie modelu zastępuje niedozwolone i nadmiarowe role przez General', () => {
    const options = imageReferenceRoleOptions(capabilities({
      max_character_reference_images: 4,
      max_object_reference_images: 10
    }))
    const items = normalizeReferenceRoles([
      { role: 'style' as const },
      { role: 'starting_image' as const },
      { role: 'starting_image' as const }
    ], options)

    expect(items.map((item) => item.role)).toEqual(['general', 'starting_image', 'general'])
  })
})
