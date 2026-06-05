import { useCallback, useState } from 'react'
import { FileText, Library, Loader2, Plus, Trash2 } from 'lucide-react'
import {
  deleteCollectionFile,
  listCollection,
  uploadCollectionFile,
  type CollectionFile,
  type Conn
} from '../lib/api'
import { fileToDataUri } from '../lib/files'
import { useHub } from '../lib/hub'
import { IconButton } from './ui/IconButton'
import { Popover } from './ui/Popover'

/**
 * M10-B5: „Project knowledge" — dokumenty wgrane do kolekcji aktywnego projektu
 * (vector store xAI), przeszukiwane narzędziem `file_search` w wielu rozmowach
 * tego projektu (na modelach grok-4). Upload/list/remove przez `/collections`.
 */
export function KnowledgePopover({ conn }: { conn: Conn }) {
  const hub = useHub()
  const [files, setFiles] = useState<CollectionFile[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const projectName = hub.projects.find((p) => p.id === hub.currentProjectId)?.name

  const load = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      const r = await listCollection(conn)
      setFiles(r.files)
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setLoading(false)
    }
  }, [conn])

  async function onPick(fileList: FileList | null): Promise<void> {
    const f = fileList?.[0]
    if (!f) return
    setBusy(true)
    setError(null)
    try {
      const uri = await fileToDataUri(f)
      await uploadCollectionFile(conn, f.name, uri)
      await load()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      await deleteCollectionFile(conn, id)
      await load()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Popover
      align="end"
      label="Project knowledge"
      trigger={({ toggle, open, triggerProps }) => (
        <IconButton
          label={files.length ? `Project knowledge (${files.length})` : 'Project knowledge'}
          icon={<Library size={18} />}
          active={open || files.length > 0}
          tooltip={!open}
          tooltipSide="bottom-end"
          onClick={() => {
            if (!open) void load() // refresh on open
            toggle()
          }}
          {...triggerProps}
        />
      )}
    >
      {() => (
        <div className="w-72 p-2">
          <div className="mb-2 truncate text-xs font-medium text-muted">
            Project knowledge{projectName ? ` · ${projectName}` : ''}
          </div>
          {!hub.currentProjectId ? (
            <p className="text-xs leading-snug text-muted">
              Select or create a project to add documents Grok can search across every chat in
              that project.
            </p>
          ) : (
            <>
              <label className="mb-2 flex cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted outline-none transition-colors hover:border-accent hover:text-fg focus-within:ring-2 focus-within:ring-accent">
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
              {loading ? (
                <p className="text-xs text-muted">Loading…</p>
              ) : files.length === 0 ? (
                <p className="text-xs text-muted">No documents yet.</p>
              ) : (
                <ul className="flex max-h-60 flex-col gap-0.5 overflow-y-auto">
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
                        onClick={() => void remove(f.id)}
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
                <p className="mt-2 text-[10px] leading-snug text-muted">
                  Grok searches these documents on grok-4 models.
                </p>
              ) : null}
            </>
          )}
          {error ? <p className="mt-2 text-[11px] text-error">{error}</p> : null}
        </div>
      )}
    </Popover>
  )
}
