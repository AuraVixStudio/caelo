import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import {
  addLspServer,
  listLspServers,
  removeLspServer,
  restartLspServer,
  type Conn,
  type LspServerInfo
} from '../../lib/api'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Field } from '../ui/Page'
import { Input } from '../ui/Input'

/** ".ts:typescript, tsx:typescriptreact" -> { ".ts":"typescript", ".tsx":"typescriptreact" } */
function parseExtensions(s: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const pair of s.split(',')) {
    const [ext, lang] = pair.split(':').map((x) => x.trim())
    if (!ext || !lang) continue
    out[ext.startsWith('.') ? ext : '.' + ext] = lang
  }
  return out
}

/** M19-B3: configure language servers (Language Server Protocol) for the coding agent. */
export function LspServers({ conn }: { conn: Conn }) {
  const [servers, setServers] = useState<LspServerInfo[]>([])
  const [hasWorkspace, setHasWorkspace] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const reload = useCallback(() => {
    listLspServers(conn)
      .then((r) => {
        setServers(r.servers)
        setHasWorkspace(r.has_workspace)
        setError(null)
      })
      .catch((e) => setError(String((e as Error)?.message || e)))
  }, [conn])

  useEffect(() => {
    reload()
  }, [reload])

  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [exts, setExts] = useState('')

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

  async function onAdd(): Promise<void> {
    const parts = command.trim().split(/\s+/).filter(Boolean)
    const extensionToLanguage = parseExtensions(exts)
    if (!name.trim() || parts.length === 0 || Object.keys(extensionToLanguage).length === 0) {
      setError('Name, command and at least one "ext:language" pair are required.')
      return
    }
    try {
      await addLspServer(conn, {
        name: name.trim(),
        command: parts[0],
        args: parts.slice(1),
        extensionToLanguage
      })
      setName('')
      setCommand('')
      setExts('')
      setError(null)
      reload()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        Language servers give the coding agent code intelligence — diagnostics after edits, go-to-definition,
        references and hover. Caelo does not bundle servers: install one yourself (e.g.{' '}
        <span className="font-mono">npm i -g pyright</span>) and make sure its command is on PATH.
      </p>

      {error ? <div className="text-sm text-red-500">{error}</div> : null}
      {!hasWorkspace ? (
        <div className="text-xs text-muted">
          Open a folder in Code to start servers — configuration is saved globally either way.
        </div>
      ) : null}

      <div className="flex flex-col gap-2">
        {servers.length === 0 ? (
          <div className="text-sm text-muted">No language servers configured yet.</div>
        ) : (
          servers.map((s) => (
            <Card key={s.name} className="flex items-center justify-between gap-3 p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{s.name}</span>
                  <Badge tone={s.running ? 'success' : 'neutral'}>
                    {s.running ? 'running' : 'stopped'}
                  </Badge>
                </div>
                <div className="truncate font-mono text-xs text-muted">{s.command}</div>
                <div className="text-xs text-muted">{s.languages.join(', ')}</div>
              </div>
              <div className="flex shrink-0 gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy === s.name || !hasWorkspace}
                  onClick={() => act(s.name, () => restartLspServer(conn, s.name))}
                >
                  <RefreshCw size={14} /> Restart
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={busy === s.name}
                  onClick={() => act(s.name, () => removeLspServer(conn, s.name))}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </Card>
          ))
        )}
      </div>

      <Card className="flex flex-col gap-3 p-4">
        <div className="text-sm font-semibold">Add a language server</div>
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="pyright" />
        </Field>
        <Field label="Command (with args)">
          <Input
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="pyright-langserver --stdio"
          />
        </Field>
        <Field label="Extensions (ext:language, comma-separated)">
          <Input value={exts} onChange={(e) => setExts(e.target.value)} placeholder=".py:python" />
        </Field>
        <div>
          <Button size="sm" onClick={onAdd}>
            Add server
          </Button>
        </div>
      </Card>
    </div>
  )
}
