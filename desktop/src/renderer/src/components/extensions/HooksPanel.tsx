import { useCallback, useEffect, useState } from 'react'
import { Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  addHook,
  clearAuditLog,
  getAuditLog,
  listHooks,
  removeHook,
  setHookEnabled,
  type AuditEntry,
  type Conn,
  type HookInfo
} from '../../lib/api'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Field } from '../ui/Page'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'

function actionTone(a: string): 'error' | 'success' | 'warn' | 'neutral' {
  if (a === 'blocked') return 'error'
  if (a === 'tool') return 'neutral'
  if (a === 'hook_script') return 'success'
  return 'warn'
}

/** M14-F4: view/enable/edit hooks (pre/post-tool) + view the audit log. */
export function HooksPanel({ conn }: { conn: Conn }) {
  const [hooks, setHooks] = useState<HookInfo[]>([])
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    listHooks(conn)
      .then((r) => setHooks(r.hooks))
      .catch((e) => setError(String(e?.message || e)))
    getAuditLog(conn, 100)
      .then((r) => setAudit(r.entries.slice().reverse()))
      .catch(() => undefined)
  }, [conn])

  useEffect(() => {
    reload()
  }, [reload])

  // add-hook form
  const [event, setEvent] = useState<HookInfo['event']>('pre_tool')
  const [htype, setHtype] = useState<HookInfo['type']>('block_command')
  const [pattern, setPattern] = useState('')
  const [command, setCommand] = useState('')
  const [matchTools, setMatchTools] = useState('')
  const [description, setDescription] = useState('')

  async function onAdd(): Promise<void> {
    const body: Partial<HookInfo> = { event, type: htype, enabled: true, description: description || undefined }
    if (htype === 'block_command' || htype === 'block_path') body.pattern = pattern
    if (htype === 'run_script') {
      body.command = command.trim().split(/\s+/).filter(Boolean)
      body.match_tools = matchTools.trim() ? matchTools.split(',').map((s) => s.trim()).filter(Boolean) : []
    }
    try {
      await addHook(conn, body)
      setPattern('')
      setCommand('')
      setMatchTools('')
      setDescription('')
      reload()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {error ? <p className="text-sm text-error">{error}</p> : null}

      <Card title="Hooks" subtitle="Deterministic, model-independent rules around tool calls.">
        <div className="flex flex-col gap-2">
          {hooks.map((h) => (
            <div key={h.id} className="flex items-center justify-between gap-3 rounded-lg bg-surface-2 px-3 py-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-fg">{h.id}</span>
                  <Badge tone="neutral">{h.event}</Badge>
                  <Badge tone="info">{h.type}</Badge>
                </div>
                <p className="mt-0.5 truncate text-xs text-muted">
                  {h.description || h.pattern || (h.command ?? []).join(' ')}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <label className="flex items-center gap-1.5 text-xs text-muted">
                  <input
                    type="checkbox"
                    checked={h.enabled}
                    onChange={(e) =>
                      setHookEnabled(conn, h.id, e.target.checked).then(reload).catch(() => undefined)
                    }
                  />
                  On
                </label>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeHook(conn, h.id).then(reload).catch(() => undefined)}
                  icon={<Trash2 size={14} />}
                  aria-label="Remove hook"
                />
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Add a hook">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Event">
              <Select value={event} onChange={(e) => setEvent(e.target.value as HookInfo['event'])}>
                <option value="pre_tool">pre_tool</option>
                <option value="post_tool">post_tool</option>
                <option value="pre_session">pre_session</option>
              </Select>
            </Field>
            <Field label="Type">
              <Select value={htype} onChange={(e) => setHtype(e.target.value as HookInfo['type'])}>
                <option value="block_command">block_command</option>
                <option value="block_path">block_path</option>
                <option value="run_script">run_script</option>
                <option value="audit">audit</option>
              </Select>
            </Field>
          </div>
          {htype === 'block_command' || htype === 'block_path' ? (
            <Field label="Pattern (regex)">
              <Input value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="rm\\s+-rf|secrets" className="font-mono text-xs" />
            </Field>
          ) : null}
          {htype === 'run_script' ? (
            <>
              <Field label="Command (argv, {path} substituted)">
                <Input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="prettier --write {path}" className="font-mono text-xs" />
              </Field>
              <Field label="Match tools (comma-separated, optional)">
                <Input value={matchTools} onChange={(e) => setMatchTools(e.target.value)} placeholder="write_file, edit_file" />
              </Field>
            </>
          ) : null}
          <Field label="Description">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this hook does" />
          </Field>
          <div>
            <Button onClick={onAdd} icon={<Plus size={15} />}>
              Add hook
            </Button>
          </div>
        </div>
      </Card>

      <Card
        title="Audit log"
        subtitle="Recent tool calls, blocks and hook scripts."
      >
        <div className="mb-3 flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={reload} icon={<RefreshCw size={14} />}>
            Refresh
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => clearAuditLog(conn).then(reload).catch(() => undefined)}
          >
            Clear
          </Button>
        </div>
        {audit.length === 0 ? (
          <p className="text-sm text-muted">No audit entries yet.</p>
        ) : (
          <div className="max-h-80 overflow-y-auto font-mono text-[11.5px]">
            {audit.map((e, i) => (
              <div key={i} className="flex items-center gap-2 border-b border-border/50 py-1">
                <span className="shrink-0 text-muted">{e.ts}</span>
                <Badge tone={actionTone(String(e.action))}>{String(e.action)}</Badge>
                <span className="truncate text-fg/90">
                  {e.tool ?? e.hook ?? ''} {e.detail ? `— ${e.detail}` : ''}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
