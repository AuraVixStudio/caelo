import { formatCost } from '../lib/genjobs'
import { Badge } from './ui/Badge'

/** Badge kosztu generacji (M11-F6, BYO-key). `approx` dla szacunku (zadanie w toku);
 *  zero/ujemny koszt → nic nie renderuje. */
export function CostBadge({
  cost,
  approx,
  tone = 'info'
}: {
  cost: number
  approx?: boolean
  tone?: 'info' | 'neutral' | 'success' | 'accent'
}) {
  const label = formatCost(cost, { approx })
  if (!label) return null
  return <Badge tone={tone}>{label}</Badge>
}
