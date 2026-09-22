// Domyślne modele w Ustawieniach → General obejmują wszystkich dostawców. Model sam
// w sobie nie mówi, czyj jest, więc grupy niosą tę informację do zapisu
// (`chat_provider`/`code_provider`).
import { describe, it, expect } from 'vitest'
import type { ModelsResp } from '../src/renderer/src/lib/api'
import {
  agentModelGroups,
  chatModelGroups,
  providerOfModel,
  resolveSelectedModel
} from '../src/renderer/src/lib/defaultModels'

function model(id: string, provider: string, media_type: string, tools = true): unknown {
  return { id, provider, media_type, is_default: false, capabilities: { supports_tools: tools } }
}

const models = {
  chat: ['grok-4.6', 'grok-4'],
  default_chat: 'grok-4.6',
  default_code: 'grok-build-0.1',
  items: [
    model('grok-4.6', 'xai', 'chat'),
    model('grok-build-0.1', 'xai', 'chat'),
    model('gemini-3.7-flash', 'google', 'chat'),
    model('gemini-3.1-flash-image', 'google', 'image', false),
    model('gpt-5.6-luna', 'openai', 'chat'),
    model('gpt-legacy', 'openai', 'chat', false)
  ]
} as unknown as ModelsResp

describe('chatModelGroups', () => {
  it('grupuje modele czatu po dostawcy i pomija media', () => {
    expect(chatModelGroups(models)).toEqual([
      { provider: 'xai', label: 'xAI', ids: ['grok-4.6', 'grok-build-0.1'] },
      { provider: 'google', label: 'Google Gemini', ids: ['gemini-3.7-flash'] },
      { provider: 'openai', label: 'OpenAI', ids: ['gpt-5.6-luna', 'gpt-legacy'] }
    ])
  })

  it('starszy backend bez `items` daje płaską listę xAI', () => {
    const legacy = { chat: ['grok-4'], items: undefined } as unknown as ModelsResp
    expect(chatModelGroups(legacy)).toEqual([
      { provider: 'xai', label: 'xAI', ids: ['grok-4'] }
    ])
  })

  it('brak odpowiedzi → brak grup (select nie ma czego pokazać)', () => {
    expect(chatModelGroups(null)).toEqual([])
  })
})

describe('agentModelGroups', () => {
  it('zostawia tylko modele z tool-callingiem', () => {
    const groups = agentModelGroups(models)
    expect(groups.find((group) => group.provider === 'openai')?.ids).toEqual(['gpt-5.6-luna'])
    expect(groups.find((group) => group.provider === 'google')?.ids).toEqual(['gemini-3.7-flash'])
  })
})

describe('providerOfModel', () => {
  it('wskazuje dostawcę wybranego modelu', () => {
    const groups = chatModelGroups(models)
    expect(providerOfModel(groups, 'gemini-3.7-flash')).toBe('google')
    expect(providerOfModel(groups, 'gpt-5.6-luna')).toBe('openai')
    expect(providerOfModel(groups, 'nieznany')).toBeNull()
  })
})

describe('resolveSelectedModel', () => {
  const groups = chatModelGroups(models)

  it('zapisany wybór wygrywa, gdy nadal istnieje', () => {
    expect(resolveSelectedModel(groups, 'gemini-3.7-flash', 'google', 'grok-4.6'))
      .toBe('gemini-3.7-flash')
  })

  it('wycofany model spada na pierwszy model zapisanego dostawcy', () => {
    expect(resolveSelectedModel(groups, 'gemini-usuniety', 'openai', 'grok-4.6'))
      .toBe('gpt-5.6-luna')
  })

  it('bez zapisanego dostawcy używa modelu domyślnego rejestru', () => {
    expect(resolveSelectedModel(groups, '', undefined, 'grok-4.6')).toBe('grok-4.6')
  })

  it('nigdy nie zwraca pustego wyboru, gdy jakiś model jest dostępny', () => {
    expect(resolveSelectedModel(groups, '', undefined, 'nieistniejacy')).toBe('grok-4.6')
    expect(resolveSelectedModel([], '', undefined, '')).toBe('')
  })
})
