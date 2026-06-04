import { memo, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, File, Folder, FolderOpen } from 'lucide-react'
import { fsTree, type Conn, type TreeEntry } from '../../lib/api'
import { cn } from '../../lib/cn'

/**
 * Węzeł drzewa (P2-4) — `memo`, by przerendery CodeView niezwiązane z drzewem
 * (odświeżenie Git po turze agenta / zapisie, toggle terminala, zmiana modelu) nie
 * kaskadowały przez całe rozwinięte poddrzewo. Propsy są stabilne: `conn` jest
 * stały w czasie życia CodeView, `onOpen` mema przez useCallback (useWorkspace),
 * a `entry`/`activePath` nie zmieniają się przy tych przerenderach.
 */
const TreeNode = memo(function TreeNode({
  conn,
  entry,
  depth,
  activePath,
  onOpen
}: {
  conn: Conn
  entry: TreeEntry
  depth: number
  activePath: string | null
  onOpen: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [children, setChildren] = useState<TreeEntry[] | null>(null)

  async function toggle(): Promise<void> {
    if (entry.type === 'file') {
      onOpen(entry.path)
      return
    }
    if (!open && children === null) {
      try {
        const t = await fsTree(conn, entry.path)
        setChildren(t.entries)
      } catch {
        setChildren([])
      }
    }
    setOpen(!open)
  }

  const isActive = entry.type === 'file' && entry.path === activePath
  const isDir = entry.type === 'dir'

  return (
    <div>
      {/* P2-6: realny <button> (fokus + Enter/Space); aria-expanded dla katalogów. */}
      <button
        type="button"
        className={cn(
          'flex w-full items-center gap-1.5 whitespace-nowrap rounded-md py-1 pr-2 text-left text-[13px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent',
          isActive ? 'bg-surface-2 text-fg' : 'text-muted hover:bg-surface-2 hover:text-fg'
        )}
        style={{ paddingLeft: 8 + depth * 12 }}
        onClick={toggle}
        title={entry.path}
        aria-expanded={isDir ? open : undefined}
      >
        {isDir ? (
          <>
            {open ? (
              <ChevronDown size={13} className="shrink-0 opacity-70" />
            ) : (
              <ChevronRight size={13} className="shrink-0 opacity-70" />
            )}
            {open ? (
              <FolderOpen size={14} className="shrink-0 text-accent" />
            ) : (
              <Folder size={14} className="shrink-0 text-accent" />
            )}
          </>
        ) : (
          <>
            <span className="w-[13px] shrink-0" />
            <File size={14} className="shrink-0 opacity-60" />
          </>
        )}
        <span className="truncate">{entry.name}</span>
      </button>
      {open && children
        ? children.map((c) => (
            <TreeNode
              key={c.path}
              conn={conn}
              entry={c}
              depth={depth + 1}
              activePath={activePath}
              onOpen={onOpen}
            />
          ))
        : null}
    </div>
  )
})

export function FileTree({
  conn,
  refreshKey,
  activePath,
  onOpen
}: {
  conn: Conn
  refreshKey: number
  activePath: string | null
  onOpen: (path: string) => void
}) {
  const [roots, setRoots] = useState<TreeEntry[]>([])

  useEffect(() => {
    fsTree(conn, '.')
      .then((t) => setRoots(t.entries))
      .catch(() => setRoots([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  return (
    <div className="px-1.5 py-1.5">
      {roots.map((e) => (
        <TreeNode
          key={e.path}
          conn={conn}
          entry={e}
          depth={0}
          activePath={activePath}
          onOpen={onOpen}
        />
      ))}
    </div>
  )
}
