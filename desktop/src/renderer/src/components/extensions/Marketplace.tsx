import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Download,
  FolderPlus,
  Globe,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload
} from 'lucide-react'
import { Share2 } from 'lucide-react'
import {
  exportPackage,
  getRegistry,
  inspectPackage,
  installPackage,
  listPackages,
  listTemplates,
  newProjectFromTemplate,
  uninstallPackage,
  type Conn,
  type InstalledPackage,
  type PackageReport,
  type RegistryEntry,
  type TemplateInfo
} from '../../lib/api'
import { downloadBase64, fileToBase64, permissionSummary, riskTone } from '../../lib/packages'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Field } from '../ui/Page'
import { Input } from '../ui/Input'
import { cn } from '../../lib/cn'

const SUBTABS = [
  { id: 'browse', label: 'Browse', icon: Globe },
  { id: 'installed', label: 'Installed', icon: Download },
  { id: 'import', label: 'Import', icon: Upload },
  { id: 'templates', label: 'Templates', icon: FolderPlus }
] as const
type SubTab = (typeof SUBTABS)[number]['id']

/** M16 — Community packages / marketplace. Browse a git-based registry, import a
 *  `.caelopkg` (skill/command/MCP/template) behind an explicit consent card, manage
 *  installed packages, and start projects from templates. Distribution over M14. */
export function Marketplace({ conn }: { conn: Conn }) {
  const [tab, setTab] = useState<SubTab>('browse')
  return (
    <div className="flex flex-col gap-5">
      <div className="flex gap-1 rounded-lg bg-surface-2 p-1">
        {SUBTABS.map((t) => {
          const Icon = t.icon
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                t.id === tab ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg'
              )}
            >
              <Icon size={14} />
              {t.label}
            </button>
          )
        })}
      </div>
      {tab === 'browse' ? <BrowseTab conn={conn} /> : null}
      {tab === 'installed' ? <InstalledTab conn={conn} /> : null}
      {tab === 'import' ? <ImportTab conn={conn} /> : null}
      {tab === 'templates' ? <TemplatesTab conn={conn} /> : null}
    </div>
  )
}

/** The consent card (M16-2): manifest, declared permissions, integrity and risk —
 *  shown BEFORE anything is installed. Install requires integrity + (for risky
 *  packages) an explicit acknowledgement checkbox. */
function ConsentCard({
  report,
  onInstall,
  onCancel,
  busy
}: {
  report: PackageReport
  onInstall: () => void
  onCancel: () => void
  busy: boolean
}) {
  const m = report.manifest
  const risky = report.risk === 'high' || m.permissions.starts_process
  const [ack, setAck] = useState(false)
  const canInstall = report.integrity_ok && (!risky || ack) && !busy
  return (
    <Card className="border-accent/40">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-fg">{m.name}</span>
            <Badge tone="neutral">{m.type}</Badge>
            <Badge tone="info">v{m.version}</Badge>
            <Badge tone={riskTone(report.risk)}>{report.risk} risk</Badge>
            <Badge tone={report.integrity_ok ? 'success' : 'error'}>
              {report.integrity_ok ? 'integrity ok' : 'integrity FAILED'}
            </Badge>
            {!report.compatible ? <Badge tone="warn">incompatible</Badge> : null}
            {report.already_installed ? <Badge tone="neutral">reinstall</Badge> : null}
          </div>
          {m.author ? <p className="mt-1 text-xs text-muted">by {m.author}</p> : null}
          {m.description ? <p className="mt-1 text-sm text-fg/80">{m.description}</p> : null}
        </div>
      </div>

      <div className="mt-4">
        <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted">
          <ShieldCheck size={13} /> Declared permissions
        </p>
        <ul className="ml-1 list-inside list-disc text-sm text-fg/80">
          {permissionSummary(m.permissions).map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </div>

      {report.warnings.length ? (
        <div className="mt-3 rounded-lg border border-warn/40 bg-warn/5 p-3">
          {report.warnings.map((w) => (
            <p key={w} className="flex items-start gap-1.5 text-xs text-warn">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              {w}
            </p>
          ))}
        </div>
      ) : null}

      {report.payload_names.length ? (
        <p className="mt-3 text-xs text-muted">
          Contents: {report.payload_names.slice(0, 8).join(', ')}
          {report.payload_names.length > 8 ? ` +${report.payload_names.length - 8} more` : ''}
        </p>
      ) : null}

      {risky ? (
        <label className="mt-3 flex items-center gap-2 text-sm text-fg">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          I trust this package and understand it can run code on my machine.
        </label>
      ) : null}

      <div className="mt-4 flex items-center gap-2">
        <Button onClick={onInstall} disabled={!canInstall}>
          Install
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        {!report.integrity_ok ? (
          <span className="text-xs text-error">Install blocked — payload integrity failed.</span>
        ) : null}
      </div>
    </Card>
  )
}

function BrowseTab({ conn }: { conn: Conn }) {
  const [url, setUrl] = useState('')
  const [entries, setEntries] = useState<RegistryEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState<PackageReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [info, setInfo] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    getRegistry(conn, url || undefined)
      .then((r) => setEntries(r.packages))
      .catch((e) => setError(String(e?.message || e)))
      .finally(() => setLoading(false))
  }, [conn, url])

  async function preview(entry: RegistryEntry): Promise<void> {
    setError(null)
    setInfo(null)
    try {
      const r = await inspectPackage(conn, { url: entry.url })
      setReport(r.report)
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  async function confirmInstall(): Promise<void> {
    if (!report) return
    setBusy(true)
    try {
      await installPackage(conn, { url: report.source_url, consent: true })
      setInfo(`Installed ${report.manifest.name}.`)
      setReport(null)
      load()
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Package registry"
        subtitle="A git/GitHub-based index — no hosted service. Leave the URL empty for the default registry."
      >
        <div className="flex items-end gap-2">
          <Field label="Registry URL (optional)">
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://raw.githubusercontent.com/…/registry.json"
            />
          </Field>
          <Button onClick={load} icon={<RefreshCw size={15} />} disabled={loading}>
            {loading ? 'Loading…' : 'Load'}
          </Button>
        </div>
      </Card>

      {error ? <p className="text-sm text-error">{error}</p> : null}
      {info ? <p className="text-sm text-success">{info}</p> : null}
      {report ? (
        <ConsentCard
          report={report}
          busy={busy}
          onInstall={confirmInstall}
          onCancel={() => setReport(null)}
        />
      ) : null}

      {entries && !entries.length ? (
        <p className="text-sm text-muted">No packages found in this registry.</p>
      ) : null}
      <div className="flex flex-col gap-2">
        {(entries || []).map((e) => (
          <Card key={`${e.type}:${e.id}`} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium text-fg">{e.name}</span>
                  <Badge tone="neutral">{e.type}</Badge>
                  {e.version ? <Badge tone="info">v{e.version}</Badge> : null}
                  {e.installed ? <Badge tone="success">installed</Badge> : null}
                  {e.has_update ? <Badge tone="warn">update</Badge> : null}
                  {!e.compatible ? <Badge tone="error">incompatible</Badge> : null}
                </div>
                <p className="mt-0.5 text-xs text-muted">{e.description || e.id}</p>
                {e.author ? <p className="mt-0.5 text-xs text-muted">by {e.author}</p> : null}
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => preview(e)}
                disabled={!e.url}
                icon={<Download size={14} />}
              >
                {e.installed ? 'Reinstall' : 'Install'}
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}

function ImportTab({ conn }: { conn: Conn }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [report, setReport] = useState<PackageReport | null>(null)
  const [pendingB64, setPendingB64] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onFile(e: React.ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setInfo(null)
    try {
      const b64 = await fileToBase64(file)
      const r = await inspectPackage(conn, { data_b64: b64 })
      setPendingB64(b64)
      setReport(r.report)
    } catch (err) {
      setError(String((err as Error)?.message || err))
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function confirmInstall(): Promise<void> {
    if (!pendingB64) return
    setBusy(true)
    try {
      const r = await installPackage(conn, { data_b64: pendingB64, consent: true })
      setInfo(`Installed ${r.installed.name} (v${r.installed.version}).`)
      setReport(null)
      setPendingB64(null)
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Import a package"
        subtitle="Open a .caelopkg file. You'll see its declared permissions and nothing installs until you confirm."
      >
        <input
          ref={fileRef}
          type="file"
          accept=".caelopkg,application/zip,application/octet-stream"
          onChange={onFile}
          className="hidden"
        />
        <Button onClick={() => fileRef.current?.click()} icon={<Upload size={15} />}>
          Choose .caelopkg file
        </Button>
      </Card>

      {error ? <p className="text-sm text-error">{error}</p> : null}
      {info ? <p className="text-sm text-success">{info}</p> : null}
      {report ? (
        <ConsentCard
          report={report}
          busy={busy}
          onInstall={confirmInstall}
          onCancel={() => {
            setReport(null)
            setPendingB64(null)
          }}
        />
      ) : null}
    </div>
  )
}

function InstalledTab({ conn }: { conn: Conn }) {
  const [packages, setPackages] = useState<InstalledPackage[]>([])
  const [updates, setUpdates] = useState<Record<string, string>>({}) // "type:id" -> latest
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    listPackages(conn)
      .then((r) => setPackages(r.packages))
      .catch((e) => setError(String(e?.message || e)))
  }, [conn])

  useEffect(() => {
    reload()
  }, [reload])

  function checkUpdates(): void {
    setError(null)
    import('../../lib/api')
      .then(({ getPackageUpdates }) => getPackageUpdates(conn))
      .then((r) => {
        const map: Record<string, string> = {}
        for (const u of r.updates) {
          if (u.has_update && u.latest_version) map[`${u.type}:${u.id}`] = u.latest_version
        }
        setUpdates(map)
      })
      .catch((e) => setError(String(e?.message || e)))
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">{packages.length} installed package(s).</p>
        <Button size="sm" variant="outline" onClick={checkUpdates} icon={<RefreshCw size={14} />}>
          Check for updates
        </Button>
      </div>
      {error ? <p className="text-sm text-error">{error}</p> : null}
      {!packages.length ? (
        <p className="text-sm text-muted">
          Nothing installed yet. Browse the registry or import a .caelopkg file.
        </p>
      ) : null}
      <div className="flex flex-col gap-2">
        {packages.map((p) => {
          const latest = updates[`${p.type}:${p.id}`]
          return (
            <Card key={`${p.type}:${p.id}`} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-medium text-fg">{p.name}</span>
                    <Badge tone="neutral">{p.type}</Badge>
                    <Badge tone="info">v{p.version}</Badge>
                    {latest ? <Badge tone="warn">update → v{latest}</Badge> : null}
                  </div>
                  <p className="mt-0.5 text-xs text-muted">
                    {p.author ? `by ${p.author} · ` : ''}installed {p.installed_at}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    uninstallPackage(conn, p.id, p.type).then(reload).catch(() => undefined)
                  }
                  icon={<Trash2 size={14} />}
                  aria-label="Uninstall"
                />
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

function TemplatesTab({ conn }: { conn: Conn }) {
  const [templates, setTemplates] = useState<TemplateInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const reload = useCallback(() => {
    listTemplates(conn)
      .then((r) => setTemplates(r.templates))
      .catch((e) => setError(String(e?.message || e)))
  }, [conn])

  useEffect(() => {
    reload()
  }, [reload])

  async function createProject(t: TemplateInfo): Promise<void> {
    setError(null)
    setInfo(null)
    const dest = await window.caelo.selectFolder()
    if (!dest) return
    setBusy(t.id)
    try {
      const r = await newProjectFromTemplate(conn, t.id, { dest, name: t.name })
      const skipped = r.template.skipped.length
      setInfo(
        `Created ${r.template.created.length} file(s) in ${r.template.dest}` +
          (skipped ? ` (${skipped} existing file(s) kept).` : '.')
      )
    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setBusy(null)
    }
  }

  // M16-4: export a template as a shareable .caelopkg bundle.
  async function onExport(t: TemplateInfo): Promise<void> {
    try {
      const r = await exportPackage(conn, { type: 'template', ref: t.id })
      downloadBase64(r.filename, r.data_b64)
    } catch (e) {
      setError(String((e as Error)?.message || e))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Project templates"
        subtitle="Scaffold a new project from a ready-made layout. You pick the destination folder."
      >
        <p className="text-xs text-muted">
          Templates only write files when you create a project — nothing runs automatically.
        </p>
      </Card>
      {error ? <p className="text-sm text-error">{error}</p> : null}
      {info ? <p className="text-sm text-success">{info}</p> : null}
      <div className="flex flex-col gap-2">
        {templates.map((t) => (
          <Card key={t.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium text-fg">{t.name}</span>
                  <Badge tone="info">v{t.version}</Badge>
                  {t.builtin ? <Badge tone="accent">built-in</Badge> : null}
                  <Badge tone="neutral">{t.file_count} files</Badge>
                </div>
                <p className="mt-0.5 text-xs text-muted">{t.description}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => createProject(t)}
                  disabled={busy === t.id}
                  icon={<FolderPlus size={14} />}
                >
                  {busy === t.id ? 'Creating…' : 'New project'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onExport(t)}
                  icon={<Share2 size={14} />}
                  aria-label="Export template"
                />
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
