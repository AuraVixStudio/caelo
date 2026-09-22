import type { ModelsResp } from './api'
import { agentModelIds } from './agentModels'
import {
  AGENT_PROVIDER_OPTIONS,
  CHAT_PROVIDER_OPTIONS,
  type AgentProvider,
  type ChatProvider
} from './providerIds'

export interface ModelGroup {
  provider: string
  label: string
  ids: string[]
}

/**
 * Domyślne modele w Ustawieniach → General obejmują WSZYSTKICH dostawców, nie tylko
 * xAI. Model sam w sobie nie mówi, czyj jest, więc zapis musi iść w parze z
 * `chat_provider`/`code_provider` — stąd grupy i `providerOfModel`.
 */
function chatIdsFor(models: ModelsResp, provider: string): string[] {
  const ids = (models.items || [])
    .filter((item) => item.media_type === 'chat' && item.provider === provider)
    .map((item) => item.id)
  // Starszy backend bez `items` zwraca tylko płaską listę xAI.
  return ids.length ? ids : provider === 'xai' ? models.chat : []
}

export function chatModelGroups(models: ModelsResp | null): ModelGroup[] {
  if (!models) return []
  return CHAT_PROVIDER_OPTIONS.map((option) => ({
    provider: option.id,
    label: option.label,
    ids: chatIdsFor(models, option.id)
  })).filter((group) => group.ids.length > 0)
}

/** Kod = tylko modele, które faktycznie umieją tool-calling (patrz `agentModelIds`). */
export function agentModelGroups(models: ModelsResp | null): ModelGroup[] {
  if (!models) return []
  return AGENT_PROVIDER_OPTIONS.map((option) => ({
    provider: option.id,
    label: option.label,
    ids: agentModelIds(models, option.id)
  })).filter((group) => group.ids.length > 0)
}

/** Dostawca wybranego modelu; `null`, gdy model nie występuje w żadnej grupie. */
export function providerOfModel(groups: ModelGroup[], id: string): string | null {
  return groups.find((group) => group.ids.includes(id))?.provider ?? null
}

/**
 * Zapisany wybór wygrywa, o ile nadal istnieje. Inaczej: model domyślny zapisanego
 * dostawcy, a na końcu pierwszy dostępny — nigdy pusty select przy dostępnych modelach.
 */
export function resolveSelectedModel(
  groups: ModelGroup[],
  saved: string | undefined,
  savedProvider: ChatProvider | AgentProvider | undefined,
  registryDefault: string
): string {
  const all = groups.flatMap((group) => group.ids)
  if (saved && all.includes(saved)) return saved
  const preferred = groups.find((group) => group.provider === savedProvider)?.ids[0]
  if (preferred) return preferred
  if (registryDefault && all.includes(registryDefault)) return registryDefault
  return all[0] || ''
}
