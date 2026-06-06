import { useCallback, useEffect, useState } from 'react'
import { Plus, Share2, Trash2 } from 'lucide-react'
import {
  addCommand,
  exportPackage,
  listCommands,
  removeCommand,
  type Conn,
  type SlashCommand
} from '../../lib/api'
import { downloadBase64 } from '../../lib/packages'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Field } from '../ui/Page'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'
import { Textarea } from '../ui/Textarea'

/** M14 (B4 mgmt): list built-in + user slash commands; add/remove user commands.
 *  Invoking them lives in the composer / palette (F3). */
export function CommandsPanel({ conn }: { conn: Conn }) {
  const [commands, setCommands] = useState<SlashCommand[]>([])
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    listCommands(conn)
      .then((r) => setCommands(r.commands))
      .catch((e) => setError(String(e?.message || e)))
  }, [conn])

  useEffect(() => {
    reload()
  }, [reload])

  const [name, setName] = useState('')
  const [target, setTarget] = useState('both')
  const [description, setDescription] = useState('')
  const [template, setTemplate] = useState('')

  async function onAdd(): Promise<void> {
    try {
      await addCommand(conn, { name: name.trim(), template, target, description: description || undefined })
      setName('')
      setDescription('')
      setTemplate('')
      reload()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  // M16-4: export a command as a shareable .caelopkg bundle.
  async function onExport(cmdName: string): Promise<void> {
    try {
      const r = await exportPackage(conn, { type: 'command', ref: cmdName })
      downloadBase64(r.filename, r.data_b64)
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {error ? <p className="text-sm text-error">{error}</p> : null}

      <Card title="Slash commands" subtitle="Type / in the chat composer to use these.">
        <div className="flex flex-col gap-2">
          {commands.map((c) => (
            <div key={c.name} className="flex items-center justify-between gap-3 rounded-lg bg-surface-2 px-3 py-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-fg">/{c.name}</span>
                  <Badge tone="neutral">{c.target}</Badge>
                  {c.mode ? <Badge tone="info">{c.mode}</Badge> : null}
                  {c.builtin ? <Badge tone="accent">built-in</Badge> : null}
                </div>
                <p className="mt-0.5 truncate text-xs text-muted">{c.description}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onExport(c.name)}
                  icon={<Share2 size={14} />}
                  aria-label="Export command"
                />
                {!c.builtin ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => removeCommand(conn, c.name).then(reload).catch(() => undefined)}
                    icon={<Trash2 size={14} />}
                    aria-label="Remove command"
                  />
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Add a command">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name (no slash)">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="summarize" />
            </Field>
            <Field label="Target">
              <Select value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="both">both</option>
                <option value="chat">chat</option>
                <option value="agent">agent</option>
              </Select>
            </Field>
          </div>
          <Field label="Description">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this command does" />
          </Field>
          <Field label="Template ({input} is replaced with your text)">
            <Textarea
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
              rows={3}
              placeholder="Summarize the following in 3 bullet points:\n\n{input}"
            />
          </Field>
          <div>
            <Button onClick={onAdd} disabled={!name.trim() || !template.trim()} icon={<Plus size={15} />}>
              Add command
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}
