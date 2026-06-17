// M19-B9: reasoning_effort selector (Auto / Low / Medium / High) shared by the chat
// composer and the coding-agent composer. '' = Auto (the backend falls back to the
// saved chat_effort / code_effort setting). Mirrors the ModeSelector dropdown style.
import { AlertTriangle, Check, ChevronDown, Gauge } from 'lucide-react'
import type { ReasoningEffort } from '../../lib/api'
import { cn } from '../../lib/cn'
import { modelSupportsEffort } from '../../lib/modelCaps'
import { Popover } from './Popover'

interface EffortOption {
  id: ReasoningEffort
  label: string
  short: string
  desc: string
}

export const EFFORT_OPTIONS: EffortOption[] = [
  { id: '', label: 'Auto', short: 'Auto', desc: 'Use the saved default (no override).' },
  { id: 'low', label: 'Low', short: 'Low', desc: 'Faster, cheaper — less reasoning.' },
  { id: 'medium', label: 'Medium', short: 'Med', desc: 'Balanced reasoning depth.' },
  { id: 'high', label: 'High', short: 'High', desc: 'Deepest reasoning — slower, costlier.' }
]

function optionFor(effort: ReasoningEffort): EffortOption {
  return EFFORT_OPTIONS.find((o) => o.id === effort) ?? EFFORT_OPTIONS[0]
}

/** Compact dropdown to pick the reasoning effort for the next turn.
 *  `side`/`align` follow the placement: a bottom composer opens upward (side="top"),
 *  a top toolbar opens downward (side="bottom") so the menu isn't clipped off-screen. */
export function EffortSelect({
  effort,
  onSelect,
  disabled = false,
  side = 'top',
  align = 'start',
  model
}: {
  effort: ReasoningEffort
  onSelect: (e: ReasoningEffort) => void
  disabled?: boolean
  side?: 'top' | 'bottom'
  align?: 'start' | 'end'
  // Wybrany model — wskazówka, czy wspiera reasoning_effort (ostrzeżenie, gdy nie).
  model?: string
}) {
  const cur = optionFor(effort)
  // Faza-G: model nie wspiera reasoning_effort → effort będzie zignorowany (backend
  // gracefully ponawia bez niego). `warnIgnored` = na triggerze pokaż, że bieżący (≠Auto)
  // wybór nic nie da; `unsupported` = w dropdownie wyjaśnij, że tryby Low/Med/High są no-op.
  const unsupported = !!model && !modelSupportsEffort(model)
  const warnIgnored = unsupported && !!effort
  return (
    <Popover
      label="Reasoning effort"
      side={side}
      align={align}
      trigger={({ toggle, open, triggerProps }) => (
        <button
          type="button"
          disabled={disabled}
          aria-label={`Reasoning effort: ${cur.label}${
            warnIgnored ? ' — not supported by the selected model (ignored)' : ''
          }`}
          onClick={toggle}
          className={cn(
            'inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-border px-2 text-xs text-fg transition-colors',
            'hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50',
            open && 'bg-surface-2'
          )}
          {...triggerProps}
        >
          <Gauge size={14} className={cn(warnIgnored && 'text-warn')} />
          <span className={cn('max-w-[56px] truncate', warnIgnored && 'text-warn')}>{cur.short}</span>
          {warnIgnored ? <AlertTriangle size={12} className="shrink-0 text-warn" /> : null}
          <ChevronDown size={12} className="opacity-60" />
        </button>
      )}
    >
      {(close) => (
        <div className="flex w-60 flex-col gap-0.5">
          <div className="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            Reasoning effort
          </div>
          {EFFORT_OPTIONS.map((o) => (
            <button
              key={o.id || 'auto'}
              onClick={() => {
                onSelect(o.id)
                close()
              }}
              className={cn(
                'flex items-start gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-surface-2',
                o.id === effort && 'bg-surface-2'
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-[13px] font-medium text-fg">
                  {o.label}
                  {o.id === effort ? <Check size={13} className="text-accent" /> : null}
                </div>
                <div className="text-[11px] text-muted">{o.desc}</div>
              </div>
            </button>
          ))}
          {unsupported ? (
            <div className="mt-1 flex items-start gap-1.5 border-t border-border px-2.5 pb-1 pt-2 text-[11px] text-warn">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>{model} ignores reasoning effort — it uses the model default.</span>
            </div>
          ) : null}
        </div>
      )}
    </Popover>
  )
}
