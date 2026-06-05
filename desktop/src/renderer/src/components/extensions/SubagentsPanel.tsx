import { useCallback, useEffect, useState } from 'react'
import { Plus, RotateCcw, Save, Trash2, Users } from 'lucide-react'
import {
  listTeamRoles,
  removeTeamRole,
  setTeamLimits,
  upsertTeamRole,
  type Conn,
  type TeamLimits,
  type TeamRole
} from '../../lib/api'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Field } from '../ui/Page'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { Textarea } from '../ui/Textarea'

// Narzędzia plikowe agenta (zakres roli przecinany z rodzicem na backendzie).
const FILE_TOOLS = ['read_file', 'list_dir', 'glob', 'grep', 'write_file', 'edit_file', 'run_command']
const MUTATING_TOOLS = new Set(['write_file', 'edit_file', 'run_command'])

// Limity edytowalne w UI (max_depth = 1 jest stałe w M17 — pokazane, nieedytowalne).
const LIMIT_FIELDS: { key: keyof TeamLimits; label: string; hint: string }[] = [
  { key: 'max_parallel', label: 'Max parallel', hint: 'Subagents running at once' },
  { key: 'max_subagents', label: 'Max subagents', hint: 'Per delegate call' },
  { key: 'max_total_turns', label: 'Turn budget', hint: 'Total LLM turns per team run' },
  { key: 'timeout_s', label: 'Timeout (s)', hint: 'Per subagent' },
  { key: 'max_iters', label: 'Max iters', hint: 'Per subagent loop' }
]

/** M17-F4: define/edit subagent roles (tool/MCP scope, worktree, model, prompt) and
 *  team limits (parallelism / budget / timeout). New runs honor the changes. */
export function SubagentsPanel({ conn }: { conn: Conn }) {
  const [roles, setRoles] = useState<TeamRole[]>([])
  const [limits, setLimits] = useState<TeamLimits | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null) // role id w edycji ('' = nowa)

  const reload = useCallback(() => {
    listTeamRoles(conn)
      .then((r) => {
        setRoles(r.roles)
        setLimits(r.limits)
      })
      .catch((e) => setError(String(e?.message || e)))
  }, [conn])

  useEffect(() => {
    reload()
  }, [reload])

  async function saveRole(role: TeamRole): Promise<void> {
    try {
      await upsertTeamRole(conn, role)
      setEditing(null)
      reload()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  async function resetRole(id: string): Promise<void> {
    try {
      await removeTeamRole(conn, id)
      setEditing(null)
      reload()
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {error ? <p className="text-sm text-error">{error}</p> : null}

      <Card
        title="Team limits"
        subtitle="Hard caps that keep a delegated run from runaway cost or resource use."
      >
        {limits ? <LimitsEditor conn={conn} limits={limits} onSaved={setLimits} /> : null}
      </Card>

      <Card
        title="Roles"
        subtitle="Each role is a subagent persona with a narrowed tool set. Mutating roles work in an isolated worktree you review at merge."
      >
        <div className="mb-3">
          <Button
            size="sm"
            icon={<Plus size={15} />}
            onClick={() => setEditing(editing === '' ? null : '')}
          >
            New role
          </Button>
        </div>
        {editing === '' ? (
          <RoleEditor
            role={blankRole()}
            onSave={saveRole}
            onCancel={() => setEditing(null)}
          />
        ) : null}
        <div className="flex flex-col gap-2">
          {roles.map((r) =>
            editing === r.id ? (
              <RoleEditor
                key={r.id}
                role={r}
                onSave={saveRole}
                onCancel={() => setEditing(null)}
                onReset={!r.builtin ? () => resetRole(r.id) : undefined}
              />
            ) : (
              <RoleRow key={r.id} role={r} onEdit={() => setEditing(r.id)} />
            )
          )}
        </div>
      </Card>
    </div>
  )
}

function blankRole(): TeamRole {
  return {
    id: '',
    label: '',
    description: '',
    tools: ['read_file', 'list_dir', 'glob', 'grep'],
    mcp: 'readonly',
    worktree: false,
    model: '',
    prompt: '',
    builtin: false
  }
}

function RoleRow({ role, onEdit }: { role: TeamRole; onEdit: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg bg-surface-2 px-3 py-2">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Users size={14} className="text-muted" />
          <span className="truncate text-sm font-medium text-fg">{role.label || role.id}</span>
          <Badge tone={role.builtin ? 'neutral' : 'info'}>{role.builtin ? 'built-in' : 'custom'}</Badge>
          {role.worktree ? <Badge tone="warn">worktree</Badge> : <Badge tone="success">read-only</Badge>}
          <Badge tone="neutral">mcp: {role.mcp}</Badge>
        </div>
        <p className="mt-0.5 truncate text-xs text-muted">{role.description || role.id}</p>
        <p className="mt-0.5 truncate font-mono text-[11px] text-muted">{role.tools.join(', ') || '(no tools)'}</p>
      </div>
      <Button variant="ghost" size="sm" onClick={onEdit}>
        Edit
      </Button>
    </div>
  )
}

function RoleEditor({
  role,
  onSave,
  onCancel,
  onReset
}: {
  role: TeamRole
  onSave: (r: TeamRole) => void
  onCancel: () => void
  onReset?: () => void
}) {
  const [draft, setDraft] = useState<TeamRole>(role)
  const isNew = role.id === ''

  function toggleTool(t: string): void {
    setDraft((d) => ({
      ...d,
      tools: d.tools.includes(t) ? d.tools.filter((x) => x !== t) : [...d.tools, t]
    }))
  }

  const mutating = draft.tools.some((t) => MUTATING_TOOLS.has(t)) || draft.mcp === 'all' || draft.worktree

  return (
    <div className="mb-2 flex flex-col gap-3 rounded-lg border border-accent/40 bg-surface px-3 py-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Role id">
          <Input
            value={draft.id}
            disabled={!isNew}
            onChange={(e) => setDraft({ ...draft, id: e.target.value.trim() })}
            placeholder="researcher"
            className="font-mono text-xs"
          />
        </Field>
        <Field label="Label">
          <Input value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} placeholder="Researcher" />
        </Field>
      </div>

      <Field label="Description">
        <Input
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          placeholder="What this role does"
        />
      </Field>

      <Field label="File tools">
        <div className="flex flex-wrap gap-2">
          {FILE_TOOLS.map((t) => (
            <label
              key={t}
              className="flex items-center gap-1.5 rounded-md bg-surface-2 px-2 py-1 font-mono text-[11px] text-fg"
            >
              <input type="checkbox" checked={draft.tools.includes(t)} onChange={() => toggleTool(t)} />
              {t}
            </label>
          ))}
        </div>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="MCP scope">
          <Select value={draft.mcp} onChange={(e) => setDraft({ ...draft, mcp: e.target.value as TeamRole['mcp'] })}>
            <option value="none">none</option>
            <option value="readonly">readonly</option>
            <option value="all">all</option>
          </Select>
        </Field>
        <Field label="Model (blank = orchestrator's)">
          <Input value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} placeholder="(inherit)" className="font-mono text-xs" />
        </Field>
      </div>

      <label className="flex items-center gap-2 text-xs text-muted">
        <input
          type="checkbox"
          checked={draft.worktree}
          onChange={(e) => setDraft({ ...draft, worktree: e.target.checked })}
        />
        Work in an isolated worktree (mutating role — changes reviewed at merge)
      </label>
      {mutating && !draft.worktree ? (
        <p className="text-[11px] text-warn">
          This role can mutate but has no worktree — its changes would not be isolated for merge review.
        </p>
      ) : null}

      <Field label="System prompt (role persona)">
        <Textarea
          value={draft.prompt}
          onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
          rows={4}
          className="font-mono text-[11.5px]"
          placeholder="You are a … subagent. …"
        />
      </Field>

      <div className="flex items-center gap-2">
        <Button size="sm" icon={<Save size={14} />} disabled={!draft.id.trim()} onClick={() => onSave(draft)}>
          Save
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <span className="flex-1" />
        {onReset ? (
          <Button variant="ghost" size="sm" icon={<RotateCcw size={14} />} onClick={onReset}>
            {role.builtin ? 'Reset to default' : 'Delete role'}
          </Button>
        ) : role.builtin && !isNew ? (
          <span className="text-[11px] text-muted">Saving overrides the built-in default.</span>
        ) : null}
      </div>
    </div>
  )
}

function LimitsEditor({
  conn,
  limits,
  onSaved
}: {
  conn: Conn
  limits: TeamLimits
  onSaved: (l: TeamLimits) => void
}) {
  const [draft, setDraft] = useState<TeamLimits>(limits)
  const [saving, setSaving] = useState(false)

  async function save(): Promise<void> {
    setSaving(true)
    try {
      const r = await setTeamLimits(conn, draft)
      setDraft(r.limits)
      onSaved(r.limits)
    } catch {
      /* ignore */
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {LIMIT_FIELDS.map((f) => (
          <Field key={f.key} label={f.label}>
            <Input
              type="number"
              value={String(draft[f.key])}
              onChange={(e) => setDraft({ ...draft, [f.key]: Number(e.target.value) || 0 })}
            />
            <span className="mt-0.5 block text-[10.5px] text-muted">{f.hint}</span>
          </Field>
        ))}
        <Field label="Max depth">
          <Input value={String(draft.max_depth)} disabled />
          <span className="mt-0.5 block text-[10.5px] text-muted">Fixed at 1 (no grandchildren)</span>
        </Field>
      </div>
      <div>
        <Button size="sm" icon={<Save size={14} />} disabled={saving} onClick={save}>
          Save limits
        </Button>
      </div>
    </div>
  )
}
