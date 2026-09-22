/** Aktywne adaptery tekstowe. Registry backendu pozostaje źródłem modeli/capabilities. */
export const CHAT_PROVIDER_OPTIONS = [
  { id: 'xai', label: 'xAI' },
  { id: 'google', label: 'Google Gemini' },
  { id: 'openai', label: 'OpenAI' }
] as const

export const AGENT_PROVIDER_OPTIONS = [
  { id: 'xai', label: 'xAI' },
  { id: 'google', label: 'Google Gemini' },
  { id: 'openai', label: 'OpenAI' }
] as const

export type ChatProvider = (typeof CHAT_PROVIDER_OPTIONS)[number]['id']
export type AgentProvider = (typeof AGENT_PROVIDER_OPTIONS)[number]['id']

const CHAT_PROVIDER_IDS: ReadonlySet<string> = new Set(
  CHAT_PROVIDER_OPTIONS.map((item) => item.id)
)
const AGENT_PROVIDER_IDS: ReadonlySet<string> = new Set(
  AGENT_PROVIDER_OPTIONS.map((item) => item.id)
)

export function isChatProvider(value: unknown): value is ChatProvider {
  return typeof value === 'string' && CHAT_PROVIDER_IDS.has(value)
}

export function isAgentProvider(value: unknown): value is AgentProvider {
  return typeof value === 'string' && AGENT_PROVIDER_IDS.has(value)
}
