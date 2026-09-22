import type { ModelsResp } from './api'
import type { AgentProvider } from './providerIds'

export type { AgentProvider } from './providerIds'

/**
 * Models usable by Code. Prefer the capability flag, but tolerate a cached
 * pre-Phase-6 registry where Gemini chat entries still said supports_tools=false.
 * The backend remains the authority and validates the selected model on send.
 */
export function agentModelIds(models: ModelsResp, provider: AgentProvider): string[] {
  const candidates = (models.items || []).filter(
    (item) => item.media_type === 'chat' && item.provider === provider
  )
  const capable = candidates.filter((item) => item.capabilities.supports_tools)
  const selected = capable.length ? capable : candidates
  if (selected.length) return selected.map((item) => item.id)
  return provider === 'xai' ? models.chat : []
}

export function defaultAgentModel(
  models: ModelsResp,
  provider: AgentProvider,
  preferred?: string | null
): string {
  const ids = agentModelIds(models, provider)
  if (preferred && ids.includes(preferred)) return preferred
  const registryDefault = (models.items || []).find(
    (item) => item.media_type === 'chat' && item.provider === provider && item.is_default
  )?.id
  if (registryDefault && ids.includes(registryDefault)) return registryDefault
  if (provider === 'xai' && ids.includes(models.default_code)) return models.default_code
  return ids[0] || ''
}
