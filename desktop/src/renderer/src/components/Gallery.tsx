import { useCallback, useEffect, useRef, useState } from 'react'
import { RotateCw } from 'lucide-react'
import { listArtifacts, type Conn, type HubArtifact } from '../lib/api'
import { useHub } from '../lib/hub'
import { ArtifactCard } from './ArtifactCard'
import { ProjectSwitcher } from './ProjectSwitcher'
import { Button } from './ui/Button'
import { Page } from './ui/Page'
import { Select } from './ui/Select'

const FILTERS = [
  { id: 'all', label: 'All media' },
  { id: 'image', label: 'Images' },
  { id: 'video', label: 'Video' }
] as const
type Filter = (typeof FILTERS)[number]['id']

/** M11-F4: jedna galeria wszystkich wygenerowanych mediów (artefakty M9). Filtr po
 *  typie + projekcie; podgląd, „Open", „Send to…". Zamyka pętlę huba — wynik dowolnego
 *  trybu twórczego jest tu przeglądalny i akcjonowalny. */
export function Gallery({ conn }: { conn: Conn }) {
  const { currentProjectId } = useHub()
  const [filter, setFilter] = useState<Filter>('all')
  const [arts, setArts] = useState<HubArtifact[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reqId = useRef(0)

  const load = useCallback(
    (f: Filter, projectId: string | null) => {
      const id = ++reqId.current
      setLoading(true)
      setError(null)
      listArtifacts(conn, {
        mode: f === 'all' ? undefined : f,
        project_id: projectId ?? undefined,
        limit: 100
      })
        .then((r) => {
          if (id !== reqId.current) return
          // Galeria pokazuje media wizualne (obraz/wideo); audio/tekst pomijamy.
          setArts(r.artifacts.filter((a) => a.type === 'image' || a.type === 'video'))
        })
        .catch((e) => {
          if (id === reqId.current) setError(String((e as Error).message || e))
        })
        .finally(() => {
          if (id === reqId.current) setLoading(false)
        })
    },
    [conn]
  )

  useEffect(() => {
    load(filter, currentProjectId)
  }, [load, filter, currentProjectId])

  return (
    <Page
      title="Gallery"
      subtitle="Every image and video you've generated — preview, open, or send to another mode."
      actions={
        <Button
          variant="outline"
          size="sm"
          icon={<RotateCw size={14} />}
          onClick={() => load(filter, currentProjectId)}
        >
          Refresh
        </Button>
      }
    >
      <div className="mb-4 flex items-center gap-2">
        <ProjectSwitcher />
        <Select
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          aria-label="Filter media"
          className="w-36"
        >
          {FILTERS.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </Select>
      </div>

      {error ? <p className="mb-4 text-sm text-error">{error}</p> : null}
      {loading ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : arts.length === 0 ? (
        <p className="text-sm text-muted">No media yet — generate an image or video.</p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
          {arts.map((a) => (
            <ArtifactCard
              key={a.id}
              conn={conn}
              art={a}
              onDeleted={(id) => setArts((prev) => prev.filter((x) => x.id !== id))}
            />
          ))}
        </div>
      )}
    </Page>
  )
}
