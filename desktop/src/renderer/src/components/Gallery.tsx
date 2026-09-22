import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Info, RotateCw, Star } from 'lucide-react'
import { listArtifacts, updateArtifact, type Conn, type HubArtifact } from '../lib/api'
import { useHub } from '../lib/hub'
import { ArtifactCard } from './ArtifactCard'
import { AssetInspector } from './AssetInspector'
import { ProjectSwitcher } from './ProjectSwitcher'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Input } from './ui/Input'
import { Page } from './ui/Page'
import { Select } from './ui/Select'

type MediaFilter = 'all' | 'image' | 'video'
type ProviderFilter = 'all' | 'xai' | 'google'

export function Gallery({ conn }: { conn: Conn }) {
  const { currentProjectId } = useHub()
  const [media, setMedia] = useState<MediaFilter>('all')
  const [provider, setProvider] = useState<ProviderFilter>('all')
  const [favorites, setFavorites] = useState(false)
  const [tag, setTag] = useState('')
  const [arts, setArts] = useState<HubArtifact[]>([])
  const [selected, setSelected] = useState<HubArtifact | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reqId = useRef(0)

  const load = useCallback(() => {
    const id = ++reqId.current
    setLoading(true); setError(null)
    listArtifacts(conn, { mode: media === 'all' ? undefined : media,
      project_id: currentProjectId ?? undefined, limit: 100 })
      .then((response) => { if (id === reqId.current) setArts(response.artifacts.filter((a) => a.type === 'image' || a.type === 'video')) })
      .catch((e) => { if (id === reqId.current) setError(String((e as Error).message || e)) })
      .finally(() => { if (id === reqId.current) setLoading(false) })
  }, [conn, currentProjectId, media])
  useEffect(load, [load])

  const visible = useMemo(() => arts.filter((art) => {
    const artProvider = typeof art.meta?.provider === 'string' ? art.meta.provider : 'xai'
    return (provider === 'all' || artProvider === provider) && (!favorites || art.favorite) &&
      (!tag.trim() || (art.tags ?? []).some((item) => item.toLowerCase().includes(tag.trim().toLowerCase())))
  }), [arts, favorites, provider, tag])
  function replace(next: HubArtifact): void {
    setArts((items) => items.map((item) => item.id === next.id ? next : item))
    setSelected((item) => item?.id === next.id ? next : item)
  }

  return (
    <Page title="Gallery" subtitle="A unified library for xAI and Google outputs, with favorites, tags, and edit lineage."
      actions={<Button variant="outline" size="sm" icon={<RotateCw size={14} />} onClick={load}>Refresh</Button>}>
      <div className="mb-4 flex flex-nowrap items-center gap-2 overflow-x-auto pb-1">
        <div className="shrink-0"><ProjectSwitcher conn={conn} /></div>
        <div className="w-32 shrink-0">
          <Select value={media} onChange={(e) => setMedia(e.target.value as MediaFilter)} aria-label="Media type">
            <option value="all">All media</option><option value="image">Images</option><option value="video">Video</option>
          </Select>
        </div>
        <div className="w-36 shrink-0">
          <Select value={provider} onChange={(e) => setProvider(e.target.value as ProviderFilter)} aria-label="Provider">
            <option value="all">All providers</option><option value="xai">xAI</option><option value="google">Google</option>
          </Select>
        </div>
        <div className="shrink-0">
          <Button variant={favorites ? 'primary' : 'outline'} size="sm" icon={<Star size={14} />} onClick={() => setFavorites((value) => !value)}>Favorites</Button>
        </div>
        <Input className="h-9 w-44 shrink-0" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="Filter by tag…" />
      </div>
      {error ? <p className="mb-4 text-sm text-error">{error}</p> : null}
      {loading ? <p className="text-sm text-muted">Loading…</p> : visible.length === 0 ? <p className="text-sm text-muted">No matching media.</p> :
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">{visible.map((art) =>
          <ArtifactCard key={art.id} conn={conn} art={art} onDeleted={(id) => setArts((items) => items.filter((x) => x.id !== id))}>
            <IconButton label={art.favorite ? 'Remove favorite' : 'Add favorite'} icon={<Star size={15} fill={art.favorite ? 'currentColor' : 'none'} />}
              onClick={() => updateArtifact(conn, art.id, { favorite: !art.favorite }).then(replace).catch((e) => setError(String(e)))} />
            <IconButton label="Inspect" icon={<Info size={15} />} onClick={() => setSelected(art)} />
          </ArtifactCard>)}</div>}
      {selected ? <AssetInspector conn={conn} artifact={selected} onClose={() => setSelected(null)} onChange={replace} /> : null}
    </Page>
  )
}
