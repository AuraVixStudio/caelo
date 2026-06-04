import { useState, type FormEvent } from 'react'
import { Check, Folder, FolderPlus, Plus } from 'lucide-react'
import { useHub } from '../lib/hub'
import { basename } from '../lib/hubQuery'
import { Button } from './ui/Button'
import { Input } from './ui/Input'
import { Popover } from './ui/Popover'

const ROW =
  'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-fg outline-none transition-colors hover:bg-surface-2 focus-visible:bg-surface-2'

/** Przełącznik projektu (M9-F6) — zawęża historię/artefakty do wybranego projektu.
 *  Listuje projekty + ostatnie workspace (otwierane jako projekt na żądanie) + „New
 *  project". Stan żyje w Hub context; zmiana woła `POST /projects/current`. */
export function ProjectSwitcher() {
  const hub = useHub()
  const [name, setName] = useState('')

  const current = hub.projects.find((p) => p.id === hub.currentProjectId) ?? null
  const projectRoots = new Set(hub.projects.map((p) => p.root).filter(Boolean))
  const candidates = hub.recentWorkspaces.filter((w) => w && !projectRoots.has(w))

  function createNamed(close: () => void): (e: FormEvent) => void {
    return (e) => {
      e.preventDefault()
      const n = name.trim()
      if (!n) return
      void hub.createProject(n)
      setName('')
      close()
    }
  }

  return (
    <Popover
      align="start"
      label="Project"
      trigger={({ toggle, open, triggerProps }) => (
        <Button
          variant="outline"
          size="sm"
          icon={<Folder size={14} />}
          onClick={toggle}
          aria-expanded={triggerProps['aria-expanded']}
          aria-haspopup={triggerProps['aria-haspopup']}
          title="Switch project"
        >
          <span className="max-w-[140px] truncate">{current ? current.name : 'All projects'}</span>
        </Button>
      )}
    >
      {(close) => (
        <div className="w-64 p-1">
          <p className="px-2 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
            Project
          </p>
          <button
            className={ROW}
            onClick={() => {
              void hub.selectProject(null)
              close()
            }}
          >
            <span className="flex w-4 justify-center">
              {!hub.currentProjectId ? <Check size={14} className="text-accent" /> : null}
            </span>
            All projects
          </button>

          {hub.projects.map((p) => (
            <button
              key={p.id}
              className={ROW}
              title={p.root || undefined}
              onClick={() => {
                void hub.selectProject(p.id)
                close()
              }}
            >
              <span className="flex w-4 justify-center">
                {p.id === hub.currentProjectId ? <Check size={14} className="text-accent" /> : null}
              </span>
              <span className="truncate">{p.name}</span>
            </button>
          ))}

          {candidates.length ? (
            <>
              <div className="my-1 border-t border-border" />
              <p className="px-2 pb-1 text-[11px] font-medium text-muted">Recent folders</p>
              {candidates.slice(0, 6).map((w) => (
                <button
                  key={w}
                  className={ROW}
                  title={w}
                  onClick={() => {
                    void hub.createProject(basename(w), w)
                    close()
                  }}
                >
                  <FolderPlus size={14} className="shrink-0 text-muted" />
                  <span className="truncate">{basename(w)}</span>
                </button>
              ))}
            </>
          ) : null}

          <div className="my-1 border-t border-border" />
          <form onSubmit={createNamed(close)} className="flex items-center gap-1 p-1">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="New project…"
              aria-label="New project name"
              className="h-8"
            />
            <Button type="submit" size="sm" icon={<Plus size={14} />} disabled={!name.trim()} />
          </form>
        </div>
      )}
    </Popover>
  )
}
