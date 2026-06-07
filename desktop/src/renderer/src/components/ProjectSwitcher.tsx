import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  ArrowLeft,
  Check,
  FileText,
  Folder,
  Loader2,
  Paperclip,
  Plus,
  Settings2,
  Trash2
} from 'lucide-react'
import {
  collectionFileDataUri,
  deleteCollectionFile,
  listCollection,
  uploadCollectionFile,
  type ChatAttachment,
  type CollectionFile,
  type Conn,
  type HubProject
} from '../lib/api'
import { fileToDataUri } from '../lib/files'
import { useHub } from '../lib/hub'
import { cn } from '../lib/cn'
import { Button } from './ui/Button'
import { Input } from './ui/Input'
import { Popover } from './ui/Popover'

const ROW =
  'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-fg outline-none transition-colors hover:bg-surface-2 focus-visible:bg-surface-2'

/**
 * Przełącznik + menedżer projektu CZATU (M9-F6 / M22). Projekty czatu są ODDZIELONE
 * od workspace'ów Code (backend filtruje `kind='chat'`), mają instrukcje (system
 * prompt) i wiedzę (dokumenty). Widok listy → wybór/„New project"; widok szczegółów
 * (ikona ⚙) → rename, instrukcje, wiedza („Attach all", gdy podano `onAttach` — tj.
 * w czacie) i usunięcie. Stan w Hub context; wiedza/kolekcje są skopowane do
 * AKTYWNEGO projektu, więc wejście w szczegóły wybiera projekt.
 */
export function ProjectSwitcher({
  conn,
  onAttach
}: {
  conn: Conn
  /** Gdy podane (czat) — pokaż wiedzę projektu + „Attach all" do composera. */
  onAttach?: (a: ChatAttachment) => void
}) {
  const hub = useHub()
  const current = hub.projects.find((p) => p.id === hub.currentProjectId) ?? null

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
      {(close) => <ProjectMenu conn={conn} onAttach={onAttach} close={close} />}
    </Popover>
  )
}

function ProjectMenu({
  conn,
  onAttach,
  close
}: {
  conn: Conn
  onAttach?: (a: ChatAttachment) => void
  close: () => void
}) {
  const hub = useHub()
  const [detailId, setDetailId] = useState<string | null>(null)
  const [name, setName] = useState('')

  const detail = detailId ? hub.projects.find((p) => p.id === detailId) ?? null : null
  if (detail) {
    return (
      <ProjectDetail
        conn={conn}
        project={detail}
        onAttach={onAttach}
        onBack={() => setDetailId(null)}
        close={close}
      />
    )
  }

  function createNamed(e: FormEvent): void {
    e.preventDefault()
    const n = name.trim()
    if (!n) return
    void hub.createProject(n)
    setName('')
    close()
  }

  return (
    <div className="w-72 p-1">
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
        <div key={p.id} className="group flex items-center">
          <button
            className={cn(ROW, 'flex-1')}
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
          <button
            type="button"
            aria-label={`Manage ${p.name}`}
            title="Manage project"
            onClick={() => setDetailId(p.id)}
            className="mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted opacity-0 outline-none transition-opacity hover:bg-surface-2 hover:text-fg focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent group-hover:opacity-100"
          >
            <Settings2 size={14} />
          </button>
        </div>
      ))}

      <div className="my-1 border-t border-border" />
      <form onSubmit={createNamed} className="flex items-center gap-1 p-1">
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
  )
}

function ProjectDetail({
  conn,
  project,
  onAttach,
  onBack,
  close
}: {
  conn: Conn
  project: HubProject
  onAttach?: (a: ChatAttachment) => void
  onBack: () => void
  close: () => void
}) {
  const hub = useHub()
  const [name, setName] = useState(project.name)
  const [instructions, setInstructions] = useState(project.instructions ?? '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  const [files, setFiles] = useState<CollectionFile[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Wejście w szczegóły wybiera projekt — wiedza/kolekcje są skopowane do aktywnego.
  useEffect(() => {
    if (hub.currentProjectId !== project.id) void hub.selectProject(project.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  const loadFiles = useCallback(async (): Promise<void> => {
    if (!onAttach) return
    try {
      const r = await listCollection(conn)
      setFiles(r.files)
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }, [conn, onAttach])

  useEffect(() => {
    void loadFiles()
  }, [loadFiles, hub.currentProjectId])

  async function save(): Promise<void> {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      await hub.updateProject(project.id, { name: name.trim() || project.name, instructions })
      setSaved(true)
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setSaving(false)
    }
  }

  async function onPick(fl: FileList | null): Promise<void> {
    const f = fl?.[0]
    if (!f) return
    setBusy(true)
    setError(null)
    try {
      const uri = await fileToDataUri(f)
      await uploadCollectionFile(conn, f.name, uri)
      await loadFiles()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function removeFile(id: string): Promise<void> {
    setBusy(true)
    try {
      await deleteCollectionFile(conn, id)
      await loadFiles()
    } catch {
      /* ignore */
    } finally {
      setBusy(false)
    }
  }

  async function attachAll(): Promise<void> {
    if (!onAttach || !files.length) return
    setBusy(true)
    setError(null)
    try {
      for (const f of files) {
        const uri = await collectionFileDataUri(conn, f.id)
        onAttach({ id: `coll:${f.id}`, name: f.name, kind: 'document', uri, mime: f.mime })
      }
      close()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function doDelete(): Promise<void> {
    setBusy(true)
    try {
      await hub.deleteProject(project.id)
      onBack()
    } catch (e) {
      setError(String((e as Error)?.message || e))
      setBusy(false)
    }
  }

  return (
    <div className="w-72 p-2">
      <div className="mb-2 flex items-center gap-1">
        <button
          type="button"
          aria-label="Back to project list"
          onClick={onBack}
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted outline-none hover:bg-surface-2 hover:text-fg focus-visible:ring-2 focus-visible:ring-accent"
        >
          <ArrowLeft size={15} />
        </button>
        <span className="truncate text-xs font-semibold text-muted">Project settings</span>
      </div>

      <label className="block px-0.5 text-[11px] font-medium text-muted">Name</label>
      <Input
        value={name}
        onChange={(e) => {
          setName(e.target.value)
          setSaved(false)
        }}
        aria-label="Project name"
        className="mt-1 h-8"
      />

      <label className="mt-2 block px-0.5 text-[11px] font-medium text-muted">
        Instructions (added to every chat in this project)
      </label>
      <textarea
        value={instructions}
        onChange={(e) => {
          setInstructions(e.target.value)
          setSaved(false)
        }}
        rows={4}
        spellCheck={false}
        placeholder="e.g. Always answer in Polish and keep responses short."
        aria-label="Project instructions"
        className="mt-1 w-full resize-y rounded-md border border-border bg-surface-2 px-2 py-1.5 text-xs text-fg outline-none focus:border-accent"
      />
      <div className="mt-1.5 flex items-center gap-2">
        <Button size="sm" onClick={() => void save()} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
        {saved ? <span className="text-[11px] text-emerald-500">Saved</span> : null}
      </div>

      {onAttach ? (
        <div className="mt-3 border-t border-border pt-2">
          <div className="mb-1.5 text-[11px] font-medium text-muted">Knowledge</div>
          <label className="mb-1.5 flex cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted outline-none transition-colors hover:border-accent hover:text-fg focus-within:ring-2 focus-within:ring-accent">
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Add document (PDF, sheet…)
            <input
              type="file"
              className="sr-only"
              aria-label="Add document to project knowledge"
              disabled={busy}
              onChange={(e) => {
                void onPick(e.target.files)
                e.target.value = ''
              }}
            />
          </label>
          {files.length === 0 ? (
            <p className="text-xs text-muted">No documents yet.</p>
          ) : (
            <ul className="flex max-h-40 flex-col gap-0.5 overflow-y-auto">
              {files.map((f) => (
                <li
                  key={f.id}
                  className="group flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs hover:bg-surface-2"
                >
                  <FileText size={13} className="shrink-0 text-muted" />
                  <span className="min-w-0 flex-1 truncate" title={f.name}>
                    {f.name}
                  </span>
                  <button
                    onClick={() => void removeFile(f.id)}
                    disabled={busy}
                    aria-label={`Remove ${f.name}`}
                    title="Remove"
                    className="shrink-0 rounded text-muted opacity-0 outline-none transition-opacity hover:text-error focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-accent group-hover:opacity-100 disabled:opacity-30"
                  >
                    <Trash2 size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {files.length > 0 ? (
            <button
              onClick={() => void attachAll()}
              disabled={busy}
              className="mt-1.5 flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg outline-none transition-colors hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Paperclip size={13} />}
              Attach all to message ({files.length})
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3 border-t border-border pt-2">
        {confirmDel ? (
          <div className="flex items-center gap-2">
            <span className="flex-1 text-[11px] text-muted">Delete project and its history?</span>
            <Button variant="danger" size="sm" onClick={() => void doDelete()} disabled={busy}>
              Delete
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmDel(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 size={13} />}
            onClick={() => setConfirmDel(true)}
            className="text-error"
          >
            Delete project
          </Button>
        )}
      </div>

      {error ? <p className="mt-2 text-[11px] text-error">{error}</p> : null}
    </div>
  )
}
