import type { ModelDescriptor, ProviderDescriptor } from '../lib/api'
import { Field } from './ui/Page'
import { Select } from './ui/Select'

export function ProviderModelPicker({
  providers,
  provider,
  onProvider,
  models,
  model,
  onModel
}: {
  providers: ProviderDescriptor[]
  provider: string
  onProvider: (value: string) => void
  models: ModelDescriptor[]
  model: string
  onModel: (value: string) => void
}) {
  return (
    <>
      <Field label="Provider" className="w-44">
        <Select aria-label="Provider" size="sm" value={provider} onChange={(e) => onProvider(e.target.value)}>
          {providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </Select>
      </Field>
      <Field label="Model" className="min-w-52 flex-1">
        <Select aria-label="Model" size="sm" value={model} onChange={(e) => onModel(e.target.value)}>
          {models.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </Select>
      </Field>
    </>
  )
}
