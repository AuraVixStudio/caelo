import { useEffect, useRef, useState } from 'react'
import { Check, Monitor, Moon, Sun } from 'lucide-react'
import {
  getAuthStatus,
  getOutputDir,
  login,
  logout,
  setOutputDir,
  type AuthResp,
  type Conn
} from '../lib/api'
import { saveSettings, useModels, useSettings } from '../lib/serverState'
import { useTheme, type ThemeMode } from '../lib/theme'
import { cn } from '../lib/cn'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { Input } from './ui/Input'
import { Page, Field } from './ui/Page'
import { Select } from './ui/Select'

function accountLabel(account: Record<string, unknown>): string {
  const email = account.email || account.preferred_username || account.name || account.sub
  return typeof email === 'string' ? email : 'xAI account'
}

const THEME_MODES: { mode: ThemeMode; label: string; icon: typeof Sun }[] = [
  { mode: 'light', label: 'Light', icon: Sun },
  { mode: 'dark', label: 'Dark', icon: Moon },
  { mode: 'system', label: 'System', icon: Monitor }
]

export function Settings({ conn }: { conn: Conn }) {
  const [auth, setAuth] = useState<AuthResp | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [hasKey, setHasKey] = useState(false)
  const [dir, setDir] = useState('')
  const [chatModels, setChatModels] = useState<string[]>([])
  const [chatModel, setChatModel] = useState('')
  const [codeModel, setCodeModel] = useState('')
  const [signingIn, setSigningIn] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // P2-2: współdzielony cache /models i /settings.
  const { models: modelsResp } = useModels(conn)
  const { settings } = useSettings(conn)
  const settingsInit = useRef(false)

  const { theme, setTheme } = useTheme()

  function refreshAuth(): void {
    void getAuthStatus(conn).then(setAuth).catch(() => undefined)
  }

  useEffect(() => {
    refreshAuth()
    void getOutputDir(conn)
      .then((r) => setDir(r.path))
      .catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // P2-2: modele ze współdzielonego cache.
  useEffect(() => {
    if (modelsResp) setChatModels(modelsResp.chat)
  }, [modelsResp])

  // Ustawienia: zaaplikuj RAZ (selecty modeli są edytowalne — kolejne odświeżenia
  // cache, np. po zapisie klucza API, nie mogą cofnąć niezapisanego wyboru).
  useEffect(() => {
    if (!settings || settingsInit.current) return
    settingsInit.current = true
    setHasKey(settings.has_api_key)
    setChatModel(settings.chat_model)
    setCodeModel(settings.code_model)
  }, [settings])

  async function signIn(): Promise<void> {
    setSigningIn(true)
    setError(null)
    setMsg('Complete the sign-in in your browser…')
    try {
      await login(conn)
      setMsg('Signed in.')
      refreshAuth()
    } catch (e) {
      setError(String((e as Error).message || e))
      setMsg(null)
    } finally {
      setSigningIn(false)
    }
  }

  async function signOut(): Promise<void> {
    await logout(conn).catch(() => undefined)
    setMsg('Signed out.')
    refreshAuth()
  }

  async function saveKey(): Promise<void> {
    if (!apiKey.trim()) return
    // P1-6: nie pokazuj „saved" po połkniętym błędzie — zgłoś faktyczny wynik.
    try {
      await saveSettings(conn, { api_key: apiKey.trim() })
      setApiKey('')
      setHasKey(true)
      setError(null)
      setMsg('API key saved.')
      refreshAuth()
    } catch (e) {
      setMsg(null)
      setError(`Could not save API key: ${String((e as Error).message || e)}`)
    }
  }

  async function browse(): Promise<void> {
    const picked = await window.grok.selectFolder()
    if (!picked) return
    try {
      await setOutputDir(conn, picked)
      setDir(picked)
      setError(null)
      setMsg('Output folder updated.')
    } catch (e) {
      setMsg(null)
      setError(`Could not update output folder: ${String((e as Error).message || e)}`)
    }
  }

  function saveModels(): void {
    saveSettings(conn, { chat_model: chatModel, code_model: codeModel })
      .then(() => {
        setError(null)
        setMsg('Model preferences saved.')
      })
      .catch((e) => {
        setMsg(null)
        setError(`Could not save model preferences: ${String((e as Error).message || e)}`)
      })
  }

  return (
    <Page
      title="Settings"
      subtitle="Account, API key, output folder and model preferences."
      maxWidth="max-w-3xl"
    >
      {msg ? <p className="mb-4 text-sm text-success">{msg}</p> : null}
      {error ? <p className="mb-4 text-sm text-error">{error}</p> : null}

      <div className="flex flex-col gap-5">
        {/* Account */}
        <Card title="xAI Account (SuperGrok / X Premium+)">
          {auth?.oauth ? (
            <>
              <p className="mb-3 text-sm text-success">✓ Signed in as {accountLabel(auth.account)}</p>
              <Button variant="danger" onClick={signOut}>
                Sign out
              </Button>
            </>
          ) : (
            <>
              <p className="mb-3 text-sm text-muted">
                Sign in via your browser to use account models without an API key.
              </p>
              <Button onClick={signIn} disabled={signingIn}>
                {signingIn ? 'Signing in…' : 'Sign in with xAI account'}
              </Button>
            </>
          )}
        </Card>

        {/* API key */}
        <Card
          title="xAI API Key"
          subtitle={`${hasKey ? 'A key is stored.' : 'No key stored.'} Used when not signed in via OAuth.`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <Input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter API key…"
              className="min-w-56 flex-1"
            />
            <Button onClick={saveKey} disabled={!apiKey.trim()}>
              Save
            </Button>
          </div>
        </Card>

        {/* Output folder */}
        <Card title="Generation Output Folder">
          <div className="flex flex-wrap items-center gap-3">
            <Input type="text" value={dir} readOnly className="min-w-56 flex-1" />
            <Button variant="outline" onClick={browse}>
              Browse
            </Button>
          </div>
        </Card>

        {/* Models */}
        <Card title="Default Models">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Chat" className="w-52">
              <Select value={chatModel} onChange={(e) => setChatModel(e.target.value)}>
                {(chatModels.length ? chatModels : chatModel ? [chatModel] : []).map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Code (agent)" className="w-52">
              <Select value={codeModel} onChange={(e) => setCodeModel(e.target.value)}>
                {[codeModel, 'grok-build-0.1', ...chatModels]
                  .filter((v, i, a) => v && a.indexOf(v) === i)
                  .map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
              </Select>
            </Field>
            <Button onClick={saveModels}>Save</Button>
          </div>
        </Card>

        {/* Appearance */}
        <Card title="Appearance" subtitle="Choose how Grok Desktop looks.">
          <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
            {THEME_MODES.map(({ mode, label, icon: Icon }) => {
              const selected = theme === mode
              return (
                <button
                  key={mode}
                  onClick={() => setTheme(mode)}
                  className={cn(
                    'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    selected
                      ? 'bg-surface text-fg shadow-sm'
                      : 'text-muted hover:text-fg'
                  )}
                >
                  <Icon size={15} />
                  {label}
                  {selected ? <Check size={14} className="text-accent" /> : null}
                </button>
              )
            })}
          </div>
        </Card>
      </div>
    </Page>
  )
}
