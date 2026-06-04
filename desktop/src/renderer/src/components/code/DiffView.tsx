import { cn } from '../../lib/cn'

// Render ujednoliconego diffa (tekst z backendu preview_change) z kolorowaniem linii.
export function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="m-0 max-h-64 overflow-auto rounded-lg bg-surface-2 py-1 font-mono text-[11.5px] leading-relaxed">
      {diff.split('\n').map((line, i) => {
        let cls = 'text-fg/80'
        if (line.startsWith('+') && !line.startsWith('+++')) cls = 'bg-success/12 text-success'
        else if (line.startsWith('-') && !line.startsWith('---')) cls = 'bg-error/12 text-error'
        else if (line.startsWith('@@')) cls = 'text-info'
        return (
          <div key={i} className={cn('whitespace-pre-wrap break-all px-2.5', cls)}>
            {line || ' '}
          </div>
        )
      })}
    </pre>
  )
}
