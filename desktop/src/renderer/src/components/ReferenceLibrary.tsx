import { useState } from 'react'
import { Maximize2, X } from 'lucide-react'
import type { StagedImage } from '../lib/hub'
import {
  VIDEO_REFERENCE_ROLE_OPTIONS,
  type ReferenceRole,
  type ReferenceRoleOption
} from '../lib/referenceRoles'
import { Select } from './ui/Select'
import { ImagePreview } from './ImagePreview'

export function ReferenceLibrary({
  items,
  max,
  onChange,
  options = VIDEO_REFERENCE_ROLE_OPTIONS
}: {
  items: StagedImage[]
  max: number
  onChange: (items: StagedImage[]) => void
  options?: ReferenceRoleOption[]
}) {
  const [preview, setPreview] = useState<StagedImage | null>(null)
  if (!items.length) return null
  return (
    <>
      <div className="flex flex-wrap gap-3">
        {items.slice(0, max).map((item, index) => (
          <div key={`${item.name}-${index}`} className="w-28 rounded-lg border border-border bg-surface p-1.5">
            <div className="group relative h-20">
              <button type="button" aria-label={`Preview ${item.name}`} onClick={() => setPreview(item)}
                className="h-full w-full overflow-hidden rounded-md">
                <img src={item.uri} alt={item.name} className="h-full w-full object-cover" />
                <span className="absolute inset-0 flex items-center justify-center bg-black/0 text-white opacity-0 transition-all group-hover:bg-black/35 group-hover:opacity-100 group-focus-within:bg-black/35 group-focus-within:opacity-100">
                  <Maximize2 size={18} />
                </span>
              </button>
              <span className="pointer-events-none absolute bottom-0 left-0 rounded-tr bg-black/70 px-1 text-[10px] text-white">&lt;IMAGE_{index + 1}&gt;</span>
              <button type="button" aria-label={`Remove ${item.name}`} onClick={() => onChange(items.filter((_, i) => i !== index))}
                className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-error text-white">
                <X size={12} />
              </button>
            </div>
            <Select size="sm" className="mt-1 w-full" value={item.role ?? options[0]?.value ?? 'general'}
              onChange={(e) => onChange(items.map((x, i) => i === index ? { ...x, role: e.target.value as ReferenceRole } : x))}>
              {options.map((option) => {
                const usedByOtherItems = items.filter((entry, itemIndex) =>
                  itemIndex !== index && entry.role === option.value).length
                return <option key={option.value} value={option.value} disabled={usedByOtherItems >= option.max}>
                  {option.label}
                </option>
              })}
            </Select>
          </div>
        ))}
      </div>
      {preview ? <ImagePreview src={preview.uri} name={preview.name} onClose={() => setPreview(null)} /> : null}
    </>
  )
}
