import { describe, expect, it } from 'vitest'
import { agentModelIds, defaultAgentModel } from '../src/renderer/src/lib/agentModels'
import type { ModelDescriptor, ModelsResp } from '../src/renderer/src/lib/api'

function model(id: string, provider: 'xai' | 'google' | 'openai', tools: boolean, isDefault = false): ModelDescriptor {
  return {
    id,
    provider,
    label: id,
    media_type: 'chat',
    status: 'stable',
    tier: 'standard',
    is_default: isDefault,
    notes: '',
    capabilities: {
      operations: ['chat'], input_modalities: ['text'], output_modalities: ['text'],
      aspect_ratios: [], resolutions: [], duration_min: null, duration_max: null,
      durations: [], supports_quality: false, quality_levels: [], max_reference_images: 0,
      max_character_reference_images: 0, max_object_reference_images: 0,
      max_style_reference_images: 0, supports_streaming: true, supports_tools: tools,
      supports_temperature: false, thinking: true, thinking_levels: ['low'],
      search_grounding: false, multi_turn: true, native_audio: false,
      supports_seed: false, first_last_frame: false, video_extension: false,
      extension_seconds: null, extension_resolutions: [], edit_uploaded_video: false,
      supports_negative_prompt: false, notes: []
    }
  }
}

const response = {
  chat: ['grok-build-0.1'], image: [], video: [], voices: [],
  default_chat: 'grok-4', default_image: '', default_video: '', default_voice: '',
  realtime_model: '', default_code: 'grok-build-0.1',
  items: [
    model('grok-build-0.1', 'xai', true, true),
    model('gemini-default', 'google', true, true),
    model('gemini-pro', 'google', true),
    model('gpt-5.6-sol', 'openai', true, true),
  ]
} satisfies ModelsResp

describe('agentModels', () => {
  it('returns all compatible Google models and honors the saved selection', () => {
    expect(agentModelIds(response, 'google')).toEqual(['gemini-default', 'gemini-pro'])
    expect(defaultAgentModel(response, 'google', 'gemini-pro')).toBe('gemini-pro')
  })

  it('uses the registry default and tolerates an older cached capability flag', () => {
    const stale = {
      ...response,
      items: [model('gemini-cached', 'google', false, true)]
    }
    expect(agentModelIds(stale, 'google')).toEqual(['gemini-cached'])
    expect(defaultAgentModel(stale, 'google')).toBe('gemini-cached')
  })

  it('returns OpenAI agent models from the same neutral registry', () => {
    expect(agentModelIds(response, 'openai')).toEqual(['gpt-5.6-sol'])
    expect(defaultAgentModel(response, 'openai')).toBe('gpt-5.6-sol')
  })
})
