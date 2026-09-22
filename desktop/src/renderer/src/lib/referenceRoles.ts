import type { ModelCapabilities } from './api'

export type ReferenceRole = 'character' | 'general' | 'object' | 'style' | 'starting_image'

export interface ReferenceRoleOption {
  value: ReferenceRole
  label: string
  max: number
}

export const VIDEO_REFERENCE_ROLE_OPTIONS: ReferenceRoleOption[] = [
  { value: 'character', label: 'Character', max: 3 },
  { value: 'object', label: 'Object', max: 3 },
  { value: 'style', label: 'Style', max: 3 }
]

export function imageReferenceRoleOptions(
  capabilities?: ModelCapabilities
): ReferenceRoleOption[] {
  const total = capabilities?.max_reference_images ?? 3
  const options: ReferenceRoleOption[] = []
  const characters = capabilities?.max_character_reference_images ?? 0
  const objects = capabilities?.max_object_reference_images ?? 0
  const styles = capabilities?.max_style_reference_images ?? 0

  if (characters > 0) options.push({ value: 'character', label: 'Character', max: characters })
  options.push({ value: 'general', label: 'General', max: total })
  if (objects > 0) options.push({ value: 'object', label: 'Object', max: objects })
  if (styles > 0) options.push({ value: 'style', label: 'Style', max: styles })
  if (capabilities?.operations.includes('edit')) {
    options.push({ value: 'starting_image', label: 'Starting Image', max: 1 })
  }
  return options
}

export function defaultReferenceRole(options: ReferenceRoleOption[]): ReferenceRole {
  return options.some((option) => option.value === 'general') ? 'general' : options[0]?.value ?? 'general'
}

export function normalizeReferenceRoles<T extends { role?: ReferenceRole }>(
  items: T[],
  options: ReferenceRoleOption[]
): T[] {
  const fallback = defaultReferenceRole(options)
  const limits = new Map(options.map((option) => [option.value, option.max]))
  const counts = new Map<ReferenceRole, number>()
  let changed = false

  const normalized = items.map((item) => {
    let role = item.role && limits.has(item.role) ? item.role : fallback
    const used = counts.get(role) ?? 0
    if (used >= (limits.get(role) ?? 0)) role = fallback
    counts.set(role, (counts.get(role) ?? 0) + 1)
    if (role === item.role) return item
    changed = true
    return { ...item, role }
  })
  return changed ? normalized : items
}
