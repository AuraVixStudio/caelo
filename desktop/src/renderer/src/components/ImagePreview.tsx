import { useEffect, useState } from 'react'
import { Maximize2, Minimize2, X } from 'lucide-react'
import { IconButton } from './ui/IconButton'

export function ImagePreview({ src, name, onClose }: {
  src: string
  name: string
  onClose: () => void
}) {
  const [actualSize, setActualSize] = useState(false)

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-[80] flex flex-col bg-black/90"
      role="dialog"
      aria-modal="true"
      aria-label={`Preview ${name}`}
      onMouseDown={(event) => { event.stopPropagation(); onClose() }}
    >
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-white/15 px-4 text-white"
        onMouseDown={(event) => event.stopPropagation()}>
        <p className="min-w-0 flex-1 truncate text-sm font-medium">{name}</p>
        <span className="hidden text-xs text-white/60 sm:inline">
          {actualSize ? 'Actual size (1:1)' : 'Fit to window'}
        </span>
        <IconButton
          label={actualSize ? 'Fit to window' : 'View actual size'}
          icon={actualSize ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
          className="text-white hover:bg-white/15 hover:text-white"
          onClick={() => setActualSize((value) => !value)}
        />
        <IconButton label="Close preview" icon={<X size={20} />}
          className="text-white hover:bg-white/15 hover:text-white" onClick={onClose} />
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex min-h-full min-w-full items-center justify-center">
          <img
            src={src}
            alt={name}
            onClick={() => setActualSize((value) => !value)}
            className={actualSize
              ? 'max-w-none cursor-zoom-out object-contain'
              : 'max-h-[calc(100vh-7rem)] max-w-full cursor-zoom-in object-contain'}
          />
        </div>
      </div>
    </div>
  )
}
