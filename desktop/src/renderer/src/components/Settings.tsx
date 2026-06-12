import { useEffect, useRef, useState } from 'react'
import { Check, Monitor, Moon, Sun } from 'lucide-react'
import {
  clearApiKey,
  getOutputDir,
  login,
  logout,
  setOutputDir,
  type ActiveSource,
  type AuthSource,
  type Conn
} from '../lib/api'
import { refreshAuth, saveSettings, useAuthStatus, useModels, useSettings } from '../lib/serverState'
import { DEFAULT_VOICE, VOICE_LANGUAGES, VOICES } from '../lib/constants'
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

// Przełącznik źródła uwierzytelniania ("tryby"): Auto = OAuth→klucz→.env.
const AUTH_SOURCES: { value: AuthSource; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'oauth', label: 'xAI account' },
  { value: 'api_key', label: 'API key' }
]

const SOURCE_LABEL: Record<ActiveSource, string> = {
  oauth: 'xAI account (OAuth)',
  api_key: 'API key',
  env: 'Environment (.env)',
  none: 'Not configured'
}

export function Settings({ conn }: { conn: Conn }) {
  const { auth } = useAuthStatus(conn)
  const [apiKey, setApiKey] = useState('')
  // Gdy klucz jest zapisany, pole pokazuje maskę kropek (sekret istnieje); klik/fokus
  // przełącza w edycję (puste pole na NOWY klucz). Klucz nigdy nie wraca z serwera.
  const [editingKey, setEditingKey] = useState(false)
  const [dir, setDir] = useState('')
  const [chatModels, setChatModels] = useState<string[]>([])
  const [chatModel, setChatModel] = useState('')
  const [codeModel, setCodeModel] = useState('')
  // M12-F4: domyślny głos/język audio (TTS, read-aloud, Talk).
  const [voice, setVoice] = useState(DEFAULT_VOICE)
  const [voiceLanguage, setVoiceLanguage] = useState('en')
  const [voiceList, setVoiceList] = useState<string[]>(VOICES.map((v) => v.id))
  const [signingIn, setSigningIn] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // P2-2: współdzielony cache /models i /settings.
  const { models: modelsResp } = useModels(conn)
  const { settings } = useSettings(conn)
  const settingsInit = useRef(false)

  const { theme, setTheme } = useTheme()

  useEffect(() => {
    void getOutputDir(conn)
      .then((r) => setDir(r.path))
      .catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // P2-2: modele ze współdzielonego cache.
  useEffect(() => {
    if (!modelsResp) return
    setChatModels(modelsResp.chat)
    if (modelsResp.voices?.length) setVoiceList(modelsResp.voices)
  }, [modelsResp])

  // Ustawienia: zaaplikuj RAZ (selecty modeli są edytowalne — kolejne odświeżenia
  // cache, np. po zapisie klucza API, nie mogą cofnąć niezapisanego wyboru).
  useEffect(() => {
    if (!settings || settingsInit.current) return
    settingsInit.current = true
    setChatModel(settings.chat_model)
    setCodeModel(settings.code_model)
    if (settings.voice) setVoice(settings.voice)
    if (settings.voice_language) setVoiceLanguage(settings.voice_language)
  }, [settings])

  async function signIn(): Promise<void> {
    setSigningIn(true)
    setError(null)
    setMsg('Complete the sign-in in your browser…')
    try {
      await login(conn)
      setMsg('Signed in.')
      void refreshAuth(conn)
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
    void refreshAuth(conn)
  }

  async function saveKey(): Promise<void> {
    if (!apiKey.trim()) return
    // P1-6: nie pokazuj „saved" po połkniętym błędzie — zgłoś faktyczny wynik.
    try {
      await saveSettings(conn, { api_key: apiKey.trim() })
      setApiKey('')
      setEditingKey(false)
      setError(null)
      setMsg('API key saved.')
      void refreshAuth(conn)
    } catch (e) {
      setMsg(null)
      setError(`Could not save API key: ${String((e as Error).message || e)}`)
    }
  }

  async function removeKey(): Promise<void> {
    try {
      await clearApiKey(conn)
      setApiKey('')
      setEditingKey(false)
      setError(null)
      setMsg('API key removed.')
      void refreshAuth(conn)
    } catch (e) {
      setMsg(null)
      setError(`Could not remove API key: ${String((e as Error).message || e)}`)
    }
  }

  async function changeSource(src: AuthSource): Promise<void> {
    try {
      await saveSettings(conn, { auth_source: src })
      setError(null)
      setMsg('Model source updated.')
      void refreshAuth(conn)
    } catch (e) {
      setMsg(null)
      setError(`Could not update model source: ${String((e as Error).message || e)}`)
    }
  }

  async function browse(): Promise<void> {
    const picked = await window.caelo.selectFolder()
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

  function saveVoice(): void {
    saveSettings(conn, { voice, voice_language: voiceLanguage })
      .then(() => {
        setError(null)
        setMsg('Voice preferences saved.')
      })
      .catch((e) => {
        setMsg(null)
        setError(`Could not save voice preferences: ${String((e as Error).message || e)}`)
      })
  }

  // Faktycznie aktywne źródło + preferencja (z fallbackiem dla starszego backendu/mocka).
  const pref: AuthSource = auth?.auth_source ?? 'auto'
  const activeSource: ActiveSource =
    auth?.active_source ?? (auth?.oauth ? 'oauth' : auth?.has_api_key ? 'api_key' : 'none')
  const hasStoredKey = auth?.has_stored_key ?? auth?.has_api_key ?? false
  const hasEnvKey = auth?.has_env_key ?? false
  // Twardy przełącznik: wybrano jawne źródło, ale nie ma dla niego poświadczeń.
  const noCredForPref = pref !== 'auto' && activeSource === 'none'
  // Maska: klucz zapisany, nie w trybie edycji, brak wpisywanego tekstu → kropki.
  const showMask = hasStoredKey && !editingKey && !apiKey

  return (
    <Page
      title="Settings"
      subtitle="Account, API key, output folder and model preferences."
      maxWidth="max-w-3xl"
    >
      {msg ? <p className="mb-4 text-sm text-success">{msg}</p> : null}
      {error ? <p className="mb-4 text-sm text-error">{error}</p> : null}

      <div className="flex flex-col gap-5">
        {/* Model source — co jest aktywne + przełącznik trybów */}
        <Card
          title="Model source"
          subtitle="Choose which credential Caelo uses for xAI calls."
        >
          <p className="mb-3 text-sm text-muted">
            Currently using:{' '}
            <span className="font-medium text-fg">{SOURCE_LABEL[activeSource]}</span>
          </p>
          {noCredForPref ? (
            // S35-b: poprawny token ostrzeżenia to `text-warn` (był nieistniejący wariant)
            <p className="mb-3 text-sm text-warn">
              {pref === 'oauth'
                ? '“xAI account” selected, but you are not signed in — sign in below, or pick another source.'
                : '“API key” selected, but no key is stored — add one below, or pick another source.'}
            </p>
          ) : null}
          <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
            {AUTH_SOURCES.map(({ value, label }) => {
              const selected = pref === value
              return (
                <button
                  key={value}
                  onClick={() => changeSource(value)}
                  className={cn(
                    'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                    selected ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg'
                  )}
                >
                  {label}
                  {selected ? <Check size={14} className="text-accent" /> : null}
                </button>
              )
            })}
          </div>
          <p className="mt-2 text-xs text-muted">
            <span className="font-medium">Auto</span> prefers your signed-in account, then a saved
            API key, then <code>.env</code>.
          </p>
        </Card>

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
          subtitle={`${hasStoredKey ? 'A key is stored.' : 'No key stored.'} Used when not signed in via OAuth.`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <Input
              type="password"
              value={showMask ? '•'.repeat(16) : apiKey}
              readOnly={showMask}
              onFocus={() => setEditingKey(true)}
              onBlur={() => {
                if (!apiKey) setEditingKey(false)
              }}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={hasStoredKey ? 'Enter a new key to replace…' : 'Enter API key…'}
              className="min-w-56 flex-1"
            />
            <Button onClick={saveKey} disabled={!apiKey.trim()}>
              Save
            </Button>
            {hasStoredKey ? (
              <Button variant="danger" onClick={removeKey}>
                Remove
              </Button>
            ) : null}
          </div>
          {hasEnvKey ? (
            <p className="mt-2 text-xs text-muted">
              A key from the environment (<code>XAI_API_KEY</code> in <code>.env</code>) is also
              present. Remove it there to stop using it.
            </p>
          ) : null}
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

        {/* Voice (M12-F4) */}
        <Card
          title="Voice"
          subtitle="Default voice and language for read-aloud, speech and the Talk pipeline."
        >
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Voice" className="w-52">
              <Select value={voice} onChange={(e) => setVoice(e.target.value)}>
                {(voiceList.length ? voiceList : [voice]).map((id) => (
                  <option key={id} value={id}>
                    {VOICES.find((v) => v.id === id)?.label || id}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Language" className="w-44">
              <Select value={voiceLanguage} onChange={(e) => setVoiceLanguage(e.target.value)}>
                {VOICE_LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Button onClick={saveVoice}>Save</Button>
          </div>
        </Card>

        {/* Appearance */}
        <Card title="Appearance" subtitle="Choose how Caelo looks.">
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
