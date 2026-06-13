import { useCallback, useEffect, useState } from 'react'
import { Play, Plug, Plus, RefreshCw, Share2, Square, Trash2 } from 'lucide-react'
import {
  addMcpServer,
  exportPackage,
  listMcpCatalog,
  listMcpServers,
  removeMcpServer,
  setMcpEnabled,
  startMcpServer,
  stopMcpServer,
  type Conn,
  type McpCatalogEntry,
  type McpServerInfo,
  type McpServerInput
} from '../../lib/api'
import { downloadBase64 } from '../../lib/packages'
import { commandPreview, missingRequired, resolveCatalogEntry } from '../../lib/mcpCatalog'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Field } from '../ui/Page'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'

function statusTone(s?: string): 'success' | 'error' | 'warn' | 'neutral' | 'info' {
  if (s === 'ready') return 'success'
  if (s === 'error') return 'error'
  if (s === 'starting') return 'warn'
  if (s === 'remote') return 'info'
  return 'neutral'
}

/** M14-F1: add/manage MCP servers, view discovered tools, enable per server. */
export function McpServers({ conn }: { conn: Conn }) {
  const [servers, setServers] = useState<McpServerInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null) // server id being acted on
  // Faza-G/TOP4: kurowany katalog MCP („one-click"). catInputs = wartości pól per wpis.
  const [catalog, setCatalog] = useState<McpCatalogEntry[]>([])
  const [catInputs, setCatInputs] = useState<Record<string, Record<string, string>>>({})
  const [catBusy, setCatBusy] = useState<string | null>(null)

  const reload = useCallback(() => {
    listMcpServers(conn)
      .then((r) => {
        setServers(r.servers)
        setError(null)
      })
      .catch((e) => setError(String(e?.message || e)))
  }, [conn])

  useEffect(() => {
    reload()
  }, [reload])

  // Faza-G/TOP4: katalog jest statyczny — pobierz raz na połączenie.
  useEffect(() => {
    listMcpCatalog(conn)
      .then((r) => setCatalog(r.catalog))
      .catch(() => setCatalog([]))
  }, [conn])

  // Add-server form state
  const [transport, setTransport] = useState<'stdio' | 'remote'>('stdio')
  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [url, setUrl] = useState('')
  const [auth, setAuth] = useState('')

  async function act(id: string, fn: () => Promise<unknown>): Promise<void> {
    setBusy(id)
    try {
      await fn()
      reload()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(null)
    }
  }

  function setCatInput(entryId: string, key: string, value: string): void {
    setCatInputs((m) => ({ ...m, [entryId]: { ...(m[entryId] ?? {}), [key]: value } }))
  }

  // Faza-G/TOP4: „install" wpisu katalogu = addMcpServer z enabled=false (NIE startuje serwera).
  // Komenda jest widoczna (consent); start to osobna, potwierdzana akcja niżej.
  async function onAddCatalog(entry: McpCatalogEntry): Promise<void> {
    const vals = catInputs[entry.id] ?? {}
    if (missingRequired(entry, vals).length > 0) return
    setCatBusy(entry.id)
    try {
      await addMcpServer(conn, resolveCatalogEntry(entry, vals))
      setCatInputs((m) => ({ ...m, [entry.id]: {} }))
      reload()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setCatBusy(null)
    }
  }

  async function onAdd(): Promise<void> {
    const body: McpServerInput =
      transport === 'stdio'
        ? { name: name || undefined, transport, command: command.trim().split(/\s+/).filter(Boolean) }
        : { name: name || undefined, transport, url: url.trim(), authorization: auth.trim() || undefined }
    try {
      await addMcpServer(conn, body)
      setName('')
      setCommand('')
      setUrl('')
      setAuth('')
      reload()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  // M16-4: export a server config as a shareable .caelopkg (secrets are stripped).
  async function onExport(id: string): Promise<void> {
    try {
      const r = await exportPackage(conn, { type: 'mcp', ref: id })
      downloadBase64(r.filename, r.data_b64)
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  const canAdd = transport === 'stdio' ? command.trim().length > 0 : url.trim().length > 0

  return (
    <div className="flex flex-col gap-5">
      {catalog.length > 0 ? (
        <Card
          title="Catalog"
          subtitle="Add a popular MCP server in one click. Installing does NOT start it — review the command, then start it yourself."
        >
          <div className="flex flex-col gap-3">
            {catalog.map((entry) => {
              const added = servers.some((s) => s.id === entry.id)
              const vals = catInputs[entry.id] ?? {}
              const blocked = missingRequired(entry, vals).length > 0
              return (
                <div key={entry.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-fg">{entry.name}</span>
                        <Badge tone="neutral">{entry.category}</Badge>
                      </div>
                      <p className="mt-0.5 text-xs text-muted">{entry.description}</p>
                    </div>
                    <div className="shrink-0">
                      {added ? (
                        <Badge tone="success">Added</Badge>
                      ) : (
                        <Button
                          size="sm"
                          disabled={catBusy === entry.id || blocked}
                          onClick={() => onAddCatalog(entry)}
                          icon={<Plus size={14} />}
                        >
                          Add
                        </Button>
                      )}
                    </div>
                  </div>
                  {!added && entry.inputs && entry.inputs.length > 0 ? (
                    <div className="mt-2 grid gap-2">
                      {entry.inputs.map((inp) => (
                        <Field key={inp.key} label={inp.label + (inp.required ? ' *' : '')}>
                          <Input
                            value={vals[inp.key] ?? ''}
                            onChange={(e) => setCatInput(entry.id, inp.key, e.target.value)}
                            placeholder={inp.placeholder}
                            type={inp.secret ? 'password' : 'text'}
                            className={inp.target === 'arg' ? 'font-mono text-xs' : undefined}
                          />
                        </Field>
                      ))}
                    </div>
                  ) : null}
                  <p className="mt-2 truncate font-mono text-[11px] text-muted">
                    {commandPreview(entry, vals)}
                  </p>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                    {entry.requires ? <span>Requires {entry.requires}</span> : null}
                    {entry.homepage ? (
                      <a
                        href={entry.homepage}
                        target="_blank"
                        rel="noreferrer"
                        className="underline hover:text-fg"
                      >
                        docs
                      </a>
                    ) : null}
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      ) : null}

      <Card title="Add an MCP server" subtitle="Connect external tools/data to chat and the agent.">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-[160px_1fr] gap-3">
            <Field label="Transport">
              <Select value={transport} onChange={(e) => setTransport(e.target.value as 'stdio' | 'remote')}>
                <option value="stdio">stdio (local)</option>
                <option value="remote">remote (xAI-side)</option>
              </Select>
            </Field>
            <Field label="Name (optional)">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Filesystem" />
            </Field>
          </div>
          {transport === 'stdio' ? (
            <Field label="Command (argv)">
              <Input
                value={command}
                onChange={(e) => setCommand(e.target.value)}
                placeholder="npx -y @modelcontextprotocol/server-filesystem C:/work"
                className="font-mono text-xs"
              />
            </Field>
          ) : (
            <>
              <Field label="Server URL">
                <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/mcp" />
              </Field>
              <Field label="Authorization (optional)">
                <Input value={auth} onChange={(e) => setAuth(e.target.value)} placeholder="Bearer …" type="password" />
              </Field>
              <p className="text-xs text-warn">
                Remote MCP runs on xAI&apos;s side: there is no local approval gate and your data is sent to xAI.
              </p>
            </>
          )}
          <div>
            <Button onClick={onAdd} disabled={!canAdd} icon={<Plug size={15} />}>
              Add server
            </Button>
          </div>
        </div>
      </Card>

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-fg">Servers</h3>
        <Button variant="ghost" size="sm" onClick={reload} icon={<RefreshCw size={14} />}>
          Refresh
        </Button>
      </div>

      {error ? <p className="text-sm text-error">{error}</p> : null}
      {servers.length === 0 ? (
        <p className="text-sm text-muted">No MCP servers configured yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {servers.map((s) => (
            <Card key={s.id} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium text-fg">{s.name}</span>
                    <Badge tone={s.transport === 'remote' ? 'info' : 'neutral'}>{s.transport}</Badge>
                    <Badge tone={statusTone(s.status)}>{s.status ?? 'stopped'}</Badge>
                  </div>
                  <p className="mt-1 truncate font-mono text-xs text-muted">
                    {s.transport === 'stdio' ? (s.command ?? []).join(' ') : s.url}
                  </p>
                  {s.error ? <p className="mt-1 text-xs text-error">{s.error}</p> : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {s.transport === 'stdio' ? (
                    s.status === 'ready' ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy === s.id}
                        onClick={() => act(s.id, () => stopMcpServer(conn, s.id))}
                        icon={<Square size={13} />}
                      >
                        Stop
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy === s.id}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Start "${s.name}"? This runs the configured command on your machine.`
                            )
                          )
                            act(s.id, () => startMcpServer(conn, s.id))
                        }}
                        icon={<Play size={13} />}
                      >
                        Start
                      </Button>
                    )
                  ) : null}
                  <label className="flex items-center gap-1.5 text-xs text-muted">
                    <input
                      type="checkbox"
                      checked={s.enabled}
                      onChange={(e) => act(s.id, () => setMcpEnabled(conn, s.id, e.target.checked))}
                    />
                    Enabled
                  </label>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onExport(s.id)}
                    icon={<Share2 size={14} />}
                    aria-label="Export server"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => act(s.id, () => removeMcpServer(conn, s.id))}
                    icon={<Trash2 size={14} />}
                    aria-label="Remove server"
                  />
                </div>
              </div>
              {s.tools && s.tools.length > 0 ? (
                <div className="mt-3 border-t border-border pt-3">
                  <p className="mb-1.5 text-xs font-medium text-muted">
                    {s.tools.length} tool{s.tools.length === 1 ? '' : 's'}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {s.tools.map((t) => (
                      <span
                        key={t.name}
                        title={t.description}
                        className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg/90"
                      >
                        {t.name}
                        {t.readonly ? <span className="ml-1 text-success">ro</span> : null}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
