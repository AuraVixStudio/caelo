import { useEffect, useState } from 'react'
import { Star, X } from 'lucide-react'
import { getArtifactLineage, updateArtifact, type Conn, type HubArtifact } from '../lib/api'
import { ArtifactMedia } from './ArtifactMedia'
import { Badge } from './ui/Badge'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Input } from './ui/Input'

export function AssetInspector({ conn, artifact, onClose, onChange }: {
  conn: Conn; artifact: HubArtifact; onClose: () => void; onChange: (artifact: HubArtifact) => void
}) {
  const [tags, setTags] = useState((artifact.tags ?? []).join(', '))
  const [lineage, setLineage] = useState<{ parents: { artifact_id: string; role: string }[]; children: { artifact_id: string; role: string }[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getArtifactLineage(conn, artifact.id).then(setLineage).catch((e) => setError(String(e))) }, [conn, artifact.id])
  async function patch(values: { favorite?: boolean; tags?: string[] }): Promise<void> {
    try { onChange(await updateArtifact(conn, artifact.id, values)); setError(null) }
    catch (e) { setError(String((e as Error).message || e)) }
  }
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/45" role="dialog" aria-modal="true" aria-label="Asset inspector" onMouseDown={onClose}>
      <aside className="h-full w-full max-w-lg overflow-y-auto border-l border-border bg-bg p-6 shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between"><div><h2 className="text-lg font-semibold">Asset inspector</h2><p className="text-xs text-muted">{artifact.id}</p></div>
          <IconButton label="Close" icon={<X size={18} />} onClick={onClose} /></div>
        <ArtifactMedia conn={conn} art={artifact} className="mb-5 max-h-72 w-full rounded-xl" />
        <div className="mb-4 flex items-center gap-2"><Badge tone="info">{String(artifact.meta?.provider || 'xai')}</Badge><Badge>{artifact.type}</Badge>
          <Button variant="outline" size="sm" icon={<Star size={14} fill={artifact.favorite ? 'currentColor' : 'none'} />}
            onClick={() => patch({ favorite: !artifact.favorite })}>{artifact.favorite ? 'Favorite' : 'Add favorite'}</Button></div>
        <label className="text-xs font-medium text-muted">Tags (comma separated)</label>
        <div className="mt-1 flex gap-2"><Input value={tags} onChange={(e) => setTags(e.target.value)} /><Button onClick={() => patch({ tags: tags.split(',').map((x) => x.trim()).filter(Boolean) })}>Save</Button></div>
        <section className="mt-6"><h3 className="mb-2 text-sm font-semibold">Lineage</h3>
          {!lineage ? <p className="text-xs text-muted">Loading…</p> : lineage.parents.length + lineage.children.length === 0 ? <p className="text-xs text-muted">Original asset — no linked sources or derivatives.</p> : <div className="space-y-2 text-xs">
            {lineage.parents.map((item) => <p key={`p-${item.artifact_id}`}><span className="text-muted">Source · {item.role}</span><br />{item.artifact_id}</p>)}
            {lineage.children.map((item) => <p key={`c-${item.artifact_id}`}><span className="text-muted">Derivative · {item.role}</span><br />{item.artifact_id}</p>)}</div>}
        </section>
        <section className="mt-6"><h3 className="mb-2 text-sm font-semibold">Metadata</h3><pre className="overflow-auto rounded-lg bg-surface p-3 text-xs text-muted">{JSON.stringify(artifact.meta, null, 2)}</pre></section>
        {artifact.path ? <p className="mt-4 break-all text-xs text-muted">{artifact.path}</p> : null}
        {error ? <p className="mt-3 text-xs text-error">{error}</p> : null}
      </aside>
    </div>
  )
}
