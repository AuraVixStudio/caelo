import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-react'
import {
  createSkill,
  deleteSkill,
  getSkill,
  listSkills,
  setSkillEnabled,
  type Conn,
  type SkillInfo
} from '../../lib/api'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Field } from '../ui/Page'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'

/** M14-F5: browse/enable/create skills (reusable workflows; Ren'Py/DAZ bundled). */
export function SkillsLibrary({ conn }: { conn: Conn }) {
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Record<string, string>>({}) // id -> body

  const reload = useCallback(() => {
    listSkills(conn)
      .then((r) => setSkills(r.skills))
      .catch((e) => setError(String(e?.message || e)))
  }, [conn])

  useEffect(() => {
    reload()
  }, [reload])

  async function toggleBody(id: string): Promise<void> {
    if (open[id] !== undefined) {
      setOpen((o) => {
        const n = { ...o }
        delete n[id]
        return n
      })
      return
    }
    try {
      const r = await getSkill(conn, id)
      setOpen((o) => ({ ...o, [id]: r.skill.body ?? '' }))
    } catch {
      /* ignore */
    }
  }

  // create-skill form
  const [newId, setNewId] = useState('')
  const [template, setTemplate] = useState('blank')
  const [newName, setNewName] = useState('')

  async function onCreate(): Promise<void> {
    try {
      await createSkill(conn, { id: newId.trim(), template, name: newName || undefined })
      setNewId('')
      setNewName('')
      reload()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {error ? <p className="text-sm text-error">{error}</p> : null}

      <Card title="Create a skill" subtitle="Reusable workflow packages, injected into the agent when enabled.">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-3">
            <Field label="Id (a-z, -, _)">
              <Input value={newId} onChange={(e) => setNewId(e.target.value)} placeholder="my-workflow" />
            </Field>
            <Field label="Template">
              <Select value={template} onChange={(e) => setTemplate(e.target.value)}>
                <option value="blank">Blank</option>
                <option value="renpy">Ren&apos;Py</option>
                <option value="daz">DAZ</option>
              </Select>
            </Field>
            <Field label="Name (optional)">
              <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="My Workflow" />
            </Field>
          </div>
          <div>
            <Button onClick={onCreate} disabled={!newId.trim()} icon={<Plus size={15} />}>
              Create skill
            </Button>
          </div>
        </div>
      </Card>

      <div className="flex flex-col gap-3">
        {skills.map((s) => (
          <Card key={s.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <button
                onClick={() => toggleBody(s.id)}
                className="flex min-w-0 items-start gap-2 text-left"
                aria-expanded={open[s.id] !== undefined}
              >
                {open[s.id] !== undefined ? (
                  <ChevronDown size={16} className="mt-0.5 shrink-0 text-muted" />
                ) : (
                  <ChevronRight size={16} className="mt-0.5 shrink-0 text-muted" />
                )}
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium text-fg">{s.name}</span>
                    {s.builtin ? <Badge tone="accent">built-in</Badge> : null}
                  </div>
                  <p className="mt-0.5 text-xs text-muted">{s.description}</p>
                </div>
              </button>
              <div className="flex shrink-0 items-center gap-2">
                <label className="flex items-center gap-1.5 text-xs text-muted">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    onChange={(e) =>
                      setSkillEnabled(conn, s.id, e.target.checked).then(reload).catch(() => undefined)
                    }
                  />
                  Enabled
                </label>
                {!s.builtin ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => deleteSkill(conn, s.id).then(reload).catch(() => undefined)}
                    icon={<Trash2 size={14} />}
                    aria-label="Delete skill"
                  />
                ) : null}
              </div>
            </div>
            {open[s.id] !== undefined ? (
              <pre className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap border-t border-border pt-3 text-xs text-fg/80">
                {open[s.id]}
              </pre>
            ) : null}
          </Card>
        ))}
      </div>
    </div>
  )
}
