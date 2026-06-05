import { RotateCw, Trash2, X } from 'lucide-react'
import type { GenJob } from '../lib/api'
import { isActive, isTerminal, jobPrompt, opLabel, statusLabel, statusTone } from '../lib/genjobs'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { CostBadge } from './CostBadge'

/** Lista zadań generacji w toku / niedawnych (M11-F5): status, postęp, koszt,
 *  anuluj (active) / ponów (failed|cancelled) / usuń z listy (zakończone).
 *  `onClear` dodaje przycisk „Clear finished" w nagłówku. Reużywana w Image/Video. */
export function GenQueue({
  jobs,
  onCancel,
  onRetry,
  onClear,
  onDismiss,
  title = 'Queue'
}: {
  jobs: GenJob[]
  onCancel: (id: string) => void
  onRetry: (id: string) => void
  onClear?: () => void
  onDismiss?: (id: string) => void
  title?: string
}) {
  if (!jobs.length) return null
  const hasFinished = jobs.some((j) => isTerminal(j.status))
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted">{title}</h2>
        {onClear && hasFinished ? (
          <Button variant="ghost" size="sm" icon={<Trash2 size={14} />} onClick={onClear}>
            Clear finished
          </Button>
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5">
        {jobs.map((j) => {
          const active = isActive(j.status)
          const retriable = j.status === 'failed' || j.status === 'cancelled'
          return (
            <div
              key={j.id}
              className="grid grid-cols-[110px_1fr_auto_auto] items-center gap-3 rounded-xl border border-border bg-surface px-4 py-2.5"
            >
              <Badge tone={statusTone(j.status)}>{statusLabel(j.status)}</Badge>
              <div className="min-w-0">
                <p className="truncate text-sm" title={jobPrompt(j)}>
                  {jobPrompt(j) || `(${opLabel(j.op)})`}
                </p>
                {j.error ? (
                  <p className="truncate text-xs text-error" title={j.error}>
                    {j.error}
                  </p>
                ) : (
                  <p className="text-xs text-muted">{opLabel(j.op)}</p>
                )}
              </div>
              <CostBadge cost={j.cost} approx={j.status !== 'done'} />
              <div className="flex items-center gap-1">
                {active ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<X size={14} />}
                    onClick={() => onCancel(j.id)}
                  >
                    Cancel
                  </Button>
                ) : null}
                {retriable ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<RotateCw size={14} />}
                    onClick={() => onRetry(j.id)}
                  >
                    Retry
                  </Button>
                ) : null}
                {!active && onDismiss ? (
                  <IconButton
                    label="Remove from list"
                    icon={<X size={14} />}
                    onClick={() => onDismiss(j.id)}
                  />
                ) : null}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
