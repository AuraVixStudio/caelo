import { Select } from './Select'

/**
 * Wspólny select modelu (P2-3) — wcześniej ten sam wzorzec
 * `models.length ? models : value ? [value] : []` powtarzał się w ChatView i
 * AgentPanel. Gdy lista modeli jeszcze nie doszła, pokazuje przynajmniej bieżącą
 * wartość, żeby select nie był pusty.
 */
export function ModelSelect({
  value,
  models,
  onChange,
  size = 'sm',
  className,
  disabled
}: {
  value: string
  models: string[]
  onChange: (value: string) => void
  size?: 'sm' | 'md'
  className?: string
  disabled?: boolean
}) {
  const options = models.length ? models : value ? [value] : []
  return (
    <Select
      size={size}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={className}
      disabled={disabled}
    >
      {options.map((m) => (
        <option key={m} value={m}>
          {m}
        </option>
      ))}
    </Select>
  )
}
