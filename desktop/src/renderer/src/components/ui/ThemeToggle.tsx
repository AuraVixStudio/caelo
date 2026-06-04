import { Check, Monitor, Moon, Sun } from 'lucide-react'
import { useTheme, type ThemeMode } from '../../lib/theme'
import { cn } from '../../lib/cn'
import { IconButton } from './IconButton'
import { Popover } from './Popover'

const MODES: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: 'light', label: 'Light', icon: Sun },
  { mode: 'dark', label: 'Dark', icon: Moon },
  { mode: 'system', label: 'System', icon: Monitor }
]

export function ThemeToggle({
  align = 'end',
  side = 'top'
}: {
  align?: 'start' | 'end'
  side?: 'bottom' | 'top'
}) {
  const { theme, setTheme } = useTheme()
  const Current = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor

  return (
    <Popover
      align={align}
      side={side}
      label="Theme"
      trigger={({ toggle, open, triggerProps }) => (
        <IconButton
          label="Theme"
          tooltip={!open}
          active={open}
          onClick={toggle}
          icon={<Current size={18} />}
          {...triggerProps}
        />
      )}
    >
      {(close) => (
        <div className="flex min-w-40 flex-col gap-0.5">
          {MODES.map(({ mode, label, icon: Icon }) => {
            const selected = theme === mode
            return (
              <button
                key={mode}
                onClick={() => {
                  setTheme(mode)
                  close()
                }}
                aria-pressed={selected}
                className={cn(
                  'flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent',
                  selected ? 'text-fg' : 'text-muted hover:bg-surface-2 hover:text-fg'
                )}
              >
                <Icon size={16} />
                <span className="flex-1 text-left">{label}</span>
                {selected ? <Check size={15} className="text-accent" /> : null}
              </button>
            )
          })}
        </div>
      )}
    </Popover>
  )
}
