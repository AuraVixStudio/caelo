import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Check, Monitor, Moon, Sun } from 'lucide-react'
import {
  clearApiKey,
  clearGoogleApiKey,
  clearOpenAIApiKey,
  getOutputDir,
  login,
  logout,
  setOutputDir,
  validateProvider,
  type ActiveSource,
  type AuthSource,
  type Conn,
  type GoogleAuthMode
} from '../lib/api'
import { refreshAuth, saveSettings, useAuthStatus, useModels, useSettings } from '../lib/serverState'
import { DEFAULT_VOICE, VOICE_LANGUAGES, VOICES } from '../lib/constants'
import { useTheme, type ThemeMode } from '../lib/theme'
import { usePersistentState } from '../lib/usePersistentState'
import { isAgentProvider, isChatProvider } from '../lib/providerIds'
import {
  agentModelGroups,
  chatModelGroups,
  providerOfModel,
  resolveSelectedModel,
  type ModelGroup
} from '../lib/defaultModels'
import { cn } from '../lib/cn'
import { Button } from './ui/Button'
import { Card } from './ui/Card'
import { Input } from './ui/Input'
import { Page, Field } from './ui/Page'
import { Select } from './ui/Select'
import { useToast } from './ui/Toast'

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

// Każdy dostawca ma własną podkartę — logowanie i klucze nie leżą już w jednej
// długiej liście, po której trzeba było scrollować, żeby dojść do OpenAI.
// Bez ikon: trzy identyczne kluczyki przy dostawcach tylko szumiły — etykiety
// same w sobie są jednoznaczne.
const TABS = [
  { id: 'xai', label: 'xAI / Grok' },
  { id: 'google', label: 'Google' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'general', label: 'General' }
] as const

type SettingsTab = (typeof TABS)[number]['id']

const isSettingsTab = (value: unknown): value is SettingsTab =>
  typeof value === 'string' && TABS.some((tab) => tab.id === value)

const settingsTabId = (id: string): string => `settings-tab-${id}`
const settingsPanelId = (id: string): string => `settings-panel-${id}`

const SOURCE_LABEL: Record<ActiveSource, string> = {
  oauth: 'xAI account (OAuth)',
  api_key: 'API key',
  env: 'Environment (.env)',
  none: 'Not configured'
}

export function Settings({ conn }: { conn: Conn }) {
  const { auth } = useAuthStatus(conn)
  const [tab, setTab] = usePersistentState<SettingsTab>('caelo.settings.tab.v1', 'xai', isSettingsTab)
  const [apiKey, setApiKey] = useState('')
  const [googleApiKey, setGoogleApiKey] = useState('')
  const [editingGoogleKey, setEditingGoogleKey] = useState(false)
  const [googleAuthMode, setGoogleAuthMode] = useState<GoogleAuthMode>('vertex')
  const [googleProjectId, setGoogleProjectId] = useState('')
  const [googleLocation, setGoogleLocation] = useState('global')
  const [googleVideoLocation, setGoogleVideoLocation] = useState('us-central1')
  const [openaiApiKey, setOpenaiApiKey] = useState('')
  const [editingOpenaiKey, setEditingOpenaiKey] = useState(false)
  const [testingOpenai, setTestingOpenai] = useState(false)
  // Gdy klucz jest zapisany, pole pokazuje maskę kropek (sekret istnieje); klik/fokus
  // przełącza w edycję (puste pole na NOWY klucz). Klucz nigdy nie wraca z serwera.
  const [editingKey, setEditingKey] = useState(false)
  const [dir, setDir] = useState('')
  // Domyślne modele obejmują wszystkich dostawców, więc trzymamy grupy (dostawca →
  // modele), a nie płaską listę xAI.
  const [chatGroups, setChatGroups] = useState<ModelGroup[]>([])
  const [codeGroups, setCodeGroups] = useState<ModelGroup[]>([])
  const [chatModel, setChatModel] = useState('')
  const [codeModel, setCodeModel] = useState('')
  // M12-F4: domyślny głos/język audio (TTS, read-aloud, Talk).
  const [voice, setVoice] = useState(DEFAULT_VOICE)
  const [voiceLanguage, setVoiceLanguage] = useState('en')
  const [voiceList, setVoiceList] = useState<string[]>(VOICES.map((v) => v.id))
  const [signingIn, setSigningIn] = useState(false)
  // ROAD-4.1-d: potwierdzenia/błędy zapisu idą w toast (fixed bottom-right), nie w
  // banner na górze strony — sekcje niżej (Voice/Output) były poza widokiem, więc
  // zapis nie dawał widocznego feedbacku.
  const toast = useToast()

  // Ten sam wzorzec WAI-ARIA co w Extensions: ←/→ przełącza podkarty.
  function onTabKey(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const direction = event.key === 'ArrowRight' ? 1 : -1
    const next = TABS[(index + direction + TABS.length) % TABS.length]
    setTab(next.id)
    document.getElementById(settingsTabId(next.id))?.focus()
  }
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
    setChatGroups(chatModelGroups(modelsResp))
    setCodeGroups(agentModelGroups(modelsResp))
    if (modelsResp.voices?.length) setVoiceList(modelsResp.voices)
  }, [modelsResp])

  // Zapisany model, którego rejestr już nie zna (np. wycofany), zostawiłby pusty
  // select. Poprawiamy WYŁĄCZNIE nieprawidłowy wybór — świeży wybór usera przechodzi
  // bez zmian, bo `resolveSelectedModel` zwraca wartość obecną na liście.
  useEffect(() => {
    if (!chatGroups.length) return
    setChatModel((current) =>
      resolveSelectedModel(chatGroups, current, settings?.chat_provider, modelsResp?.default_chat || '')
    )
  }, [chatGroups, modelsResp?.default_chat, settings?.chat_provider])

  useEffect(() => {
    if (!codeGroups.length) return
    setCodeModel((current) =>
      resolveSelectedModel(codeGroups, current, settings?.code_provider, modelsResp?.default_code || '')
    )
  }, [codeGroups, modelsResp?.default_code, settings?.code_provider])

  // Ustawienia: zaaplikuj RAZ (selecty modeli są edytowalne — kolejne odświeżenia
  // cache, np. po zapisie klucza API, nie mogą cofnąć niezapisanego wyboru).
  useEffect(() => {
    if (!settings || settingsInit.current) return
    settingsInit.current = true
    setChatModel(settings.chat_model)
    setCodeModel(settings.code_model)
    if (settings.voice) setVoice(settings.voice)
    if (settings.voice_language) setVoiceLanguage(settings.voice_language)
    setGoogleAuthMode(settings.google_auth_mode || 'vertex')
    setGoogleProjectId(settings.google_project_id || '')
    setGoogleLocation(settings.google_location || 'global')
    setGoogleVideoLocation(settings.google_video_location || 'us-central1')
  }, [settings])

  async function signIn(): Promise<void> {
    setSigningIn(true)
    toast.push('Complete the sign-in in your browser…', 'info')
    try {
      await login(conn)
      toast.push('Signed in.', 'success')
      void refreshAuth(conn)
    } catch (e) {
      toast.push(String((e as Error).message || e), 'error')
    } finally {
      setSigningIn(false)
    }
  }

  async function signOut(): Promise<void> {
    await logout(conn).catch(() => undefined)
    toast.push('Signed out.', 'success')
    void refreshAuth(conn)
  }

  async function saveKey(): Promise<void> {
    if (!apiKey.trim()) return
    // P1-6: nie pokazuj „saved" po połkniętym błędzie — zgłoś faktyczny wynik.
    try {
      await saveSettings(conn, { api_key: apiKey.trim() })
      setApiKey('')
      setEditingKey(false)
      toast.push('API key saved.', 'success')
      void refreshAuth(conn)
    } catch (e) {
      toast.push(`Could not save API key: ${String((e as Error).message || e)}`, 'error')
    }
  }

  async function removeKey(): Promise<void> {
    try {
      await clearApiKey(conn)
      setApiKey('')
      setEditingKey(false)
      toast.push('API key removed.', 'success')
      void refreshAuth(conn)
    } catch (e) {
      toast.push(`Could not remove API key: ${String((e as Error).message || e)}`, 'error')
    }
  }

  async function changeSource(src: AuthSource): Promise<void> {
    try {
      await saveSettings(conn, { auth_source: src })
      toast.push('Model source updated.', 'success')
      void refreshAuth(conn)
    } catch (e) {
      toast.push(`Could not update model source: ${String((e as Error).message || e)}`, 'error')
    }
  }

  async function saveGoogle(): Promise<void> {
    try {
      await saveSettings(conn, {
        google_auth_mode: googleAuthMode,
        google_project_id: googleProjectId.trim(),
        google_location: googleLocation.trim(),
        google_video_location: googleVideoLocation.trim(),
        ...(googleApiKey.trim() ? { google_api_key: googleApiKey.trim() } : {})
      })
      setGoogleApiKey('')
      setEditingGoogleKey(false)
      toast.push('Google configuration saved.', 'success')
    } catch (e) {
      toast.push(`Could not save Google configuration: ${String((e as Error).message || e)}`, 'error')
    }
  }

  async function removeGoogleKey(): Promise<void> {
    try {
      await clearGoogleApiKey(conn)
      setGoogleApiKey('')
      setEditingGoogleKey(false)
      toast.push('Google AI Studio key removed.', 'success')
    } catch (e) {
      toast.push(`Could not remove Google key: ${String((e as Error).message || e)}`, 'error')
    }
  }

  async function saveOpenAIKey(): Promise<void> {
    if (!openaiApiKey.trim()) return
    try {
      await saveSettings(conn, { openai_api_key: openaiApiKey.trim() })
      setOpenaiApiKey('')
      setEditingOpenaiKey(false)
      toast.push('OpenAI API key saved.', 'success')
    } catch (e) {
      toast.push(`Could not save OpenAI key: ${String((e as Error).message || e)}`, 'error')
    }
  }

  async function removeOpenAIKey(): Promise<void> {
    try {
      await clearOpenAIApiKey(conn)
      setOpenaiApiKey('')
      setEditingOpenaiKey(false)
      toast.push('OpenAI API key removed.', 'success')
    } catch (e) {
      toast.push(`Could not remove OpenAI key: ${String((e as Error).message || e)}`, 'error')
    }
  }

  async function testOpenAI(): Promise<void> {
    setTestingOpenai(true)
    try {
      const result = await validateProvider(conn, 'openai')
      const count = Number(result.available_model_count || 0)
      toast.push(`OpenAI connection works${count ? ` — ${count} models available.` : '.'}`, 'success')
    } catch (e) {
      toast.push(`OpenAI connection failed: ${String((e as Error).message || e)}`, 'error')
    } finally {
      setTestingOpenai(false)
    }
  }

  async function browse(): Promise<void> {
    const picked = await window.caelo.selectFolder()
    if (!picked) return
    try {
      await setOutputDir(conn, picked)
      setDir(picked)
      toast.push('Output folder updated.', 'success')
    } catch (e) {
      toast.push(`Could not update output folder: ${String((e as Error).message || e)}`, 'error')
    }
  }

  function saveModels(): void {
    // Sam identyfikator modelu nie mówi, czyj jest — zapisujemy go razem z dostawcą,
    // inaczej Chat/Code wróciłyby do xAI mimo wybrania modelu Google czy OpenAI.
    const chatProvider = providerOfModel(chatGroups, chatModel)
    const codeProvider = providerOfModel(codeGroups, codeModel)
    saveSettings(conn, {
      chat_model: chatModel,
      code_model: codeModel,
      ...(isChatProvider(chatProvider) ? { chat_provider: chatProvider } : {}),
      ...(isAgentProvider(codeProvider) ? { code_provider: codeProvider } : {})
    })
      .then(() => {
        toast.push('Model preferences saved.', 'success')
      })
      .catch((e) => {
        toast.push(`Could not save model preferences: ${String((e as Error).message || e)}`, 'error')
      })
  }

  function saveVoice(): void {
    saveSettings(conn, { voice, voice_language: voiceLanguage })
      .then(() => {
        toast.push('Voice preferences saved.', 'success')
      })
      .catch((e) => {
        toast.push(`Could not save voice preferences: ${String((e as Error).message || e)}`, 'error')
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
  const showGoogleMask = Boolean(settings?.google_has_api_key) && !editingGoogleKey && !googleApiKey
  const showOpenaiMask = Boolean(settings?.openai_has_api_key) && !editingOpenaiKey && !openaiApiKey

  return (
    <Page
      title="Settings"
      subtitle="Account, API key, output folder and model preferences."
      maxWidth="max-w-3xl"
    >
      <div className="flex flex-col gap-5">
        <Card
          title="Privacy and credentials"
          subtitle="Your saved provider keys and xAI session are encrypted by the operating system."
        >
          <p className="text-sm text-muted">
            Caelo has no proxy or telemetry. Prompts, attachments and generated media are sent
            directly to the provider selected for that request: <span className="text-fg">xAI</span>,{' '}
            <span className="text-fg">Google</span> or <span className="text-fg">OpenAI</span>.
            Saved secrets are never written as plain
            text or returned to this interface after saving.
          </p>
        </Card>
        <div className="flex gap-1 border-b border-border" role="tablist" aria-label="Settings sections">
          {TABS.map((entry, index) => {
            const active = entry.id === tab
            return (
              <button
                key={entry.id}
                id={settingsTabId(entry.id)}
                role="tab"
                aria-selected={active}
                aria-controls={settingsPanelId(entry.id)}
                tabIndex={active ? 0 : -1}
                onClick={() => setTab(entry.id)}
                onKeyDown={(event) => onTabKey(event, index)}
                className={cn(
                  'flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors',
                  active ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-fg'
                )}
              >
                {entry.label}
              </button>
            )
          })}
        </div>

        {tab === 'xai' ? (
          <div
            role="tabpanel"
            id={settingsPanelId('xai')}
            aria-labelledby={settingsTabId('xai')}
            className="flex flex-col gap-5"
          >
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

        {/* Models */}
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

          </div>
        ) : null}

        {tab === 'google' ? (
          <div
            role="tabpanel"
            id={settingsPanelId('google')}
            aria-labelledby={settingsTabId('google')}
            className="flex flex-col gap-5"
          >
        {/* Google media authentication (Faza 2). */}
        <Card
          title="Google Gemini / Vertex AI"
          subtitle="Used for Nano Banana images and Gemini Omni or Veo video."
        >
          <div className="flex flex-col gap-3">
            <Field label="Authentication">
              <Select value={googleAuthMode} onChange={(e) => setGoogleAuthMode(e.target.value as GoogleAuthMode)}>
                <option value="vertex">Google Cloud project (ADC)</option>
                <option value="ai_studio">Google AI Studio API key</option>
              </Select>
            </Field>
            {googleAuthMode === 'vertex' ? (
              <>
                <Field label="Cloud project ID">
                  <Input value={googleProjectId} onChange={(e) => setGoogleProjectId(e.target.value)} placeholder="my-google-cloud-project" />
                </Field>
                <div className="flex gap-3">
                  <Field label="Image location" className="flex-1">
                    <Input value={googleLocation} onChange={(e) => setGoogleLocation(e.target.value)} placeholder="global" />
                  </Field>
                  <Field label="Video location" className="flex-1">
                    <Input value={googleVideoLocation} onChange={(e) => setGoogleVideoLocation(e.target.value)} placeholder="us-central1" />
                  </Field>
                </div>
                <p className="text-xs text-muted">
                  Uses Application Default Credentials from Google Cloud SDK. Run <code>gcloud auth application-default login</code> when the session expires.
                </p>
              </>
            ) : (
              <div className="flex flex-wrap items-end gap-3">
                <Field label="AI Studio API key" className="min-w-56 flex-1">
                  <Input
                    type="password"
                    value={showGoogleMask ? '•'.repeat(16) : googleApiKey}
                    readOnly={showGoogleMask}
                    onFocus={() => setEditingGoogleKey(true)}
                    onBlur={() => { if (!googleApiKey) setEditingGoogleKey(false) }}
                    onChange={(e) => setGoogleApiKey(e.target.value)}
                    placeholder={settings?.google_has_api_key ? 'Enter a new key to replace…' : 'Enter Google API key…'}
                  />
                </Field>
                {settings?.google_has_api_key ? (
                  <Button variant="danger" onClick={removeGoogleKey}>Remove</Button>
                ) : null}
              </div>
            )}
            <div><Button onClick={saveGoogle}>Save Google settings</Button></div>
          </div>
        </Card>

          </div>
        ) : null}

        {tab === 'openai' ? (
          <div
            role="tabpanel"
            id={settingsPanelId('openai')}
            aria-labelledby={settingsTabId('openai')}
            className="flex flex-col gap-5"
          >
        <Card
          title="OpenAI API"
          subtitle="Used for GPT models in Chat and Code. A ChatGPT subscription is not used for API authentication."
        >
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted">
              Credential source:{' '}
              <span className="font-medium text-fg">
                {settings?.openai_auth_source === 'vault'
                  ? 'Encrypted vault'
                  : settings?.openai_auth_source === 'env'
                    ? 'OPENAI_API_KEY environment variable'
                    : 'Not configured'}
              </span>
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="OpenAI API key" className="min-w-56 flex-1">
                <Input
                  type="password"
                  value={showOpenaiMask ? '•'.repeat(16) : openaiApiKey}
                  readOnly={showOpenaiMask}
                  onFocus={() => setEditingOpenaiKey(true)}
                  onBlur={() => { if (!openaiApiKey) setEditingOpenaiKey(false) }}
                  onChange={(e) => setOpenaiApiKey(e.target.value)}
                  placeholder={settings?.openai_has_api_key
                    ? 'Enter a new key to replace…'
                    : 'Enter OpenAI API key…'}
                />
              </Field>
              <Button onClick={saveOpenAIKey} disabled={!openaiApiKey.trim()}>Save</Button>
              {settings?.openai_auth_source === 'vault' ? (
                <Button variant="danger" onClick={removeOpenAIKey}>Remove</Button>
              ) : null}
              <Button variant="outline" onClick={testOpenAI} disabled={testingOpenai}>
                {testingOpenai ? 'Testing…' : 'Test connection'}
              </Button>
            </div>
            <p className="text-xs text-muted">
              Caelo uses the OpenAI API with local conversation history and does not reuse browser
              cookies or a ChatGPT sign-in.
            </p>
          </div>
        </Card>

          </div>
        ) : null}

        {tab === 'general' ? (
          <div
            role="tabpanel"
            id={settingsPanelId('general')}
            aria-labelledby={settingsTabId('general')}
            className="flex flex-col gap-5"
          >
        <Card
          title="Default Models"
          subtitle="Starting model for a new chat and for the coding agent — from any configured provider."
        >
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Chat" className="w-60">
              <Select aria-label="Default chat model" value={chatModel}
                onChange={(e) => setChatModel(e.target.value)}>
                {chatGroups.map((group) => (
                  <optgroup key={group.provider} label={group.label}>
                    {group.ids.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </Select>
            </Field>
            <Field label="Code (agent)" className="w-60">
              <Select aria-label="Default code model" value={codeModel}
                onChange={(e) => setCodeModel(e.target.value)}>
                {codeGroups.map((group) => (
                  <optgroup key={group.provider} label={group.label}>
                    {group.ids.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </Select>
            </Field>
            <Button onClick={saveModels}>Save</Button>
          </div>
          <p className="mt-3 text-xs text-muted">
            Code lists only models that support tool calling. Chat and Code panels can still
            switch provider per conversation.
          </p>
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
        ) : null}
      </div>
    </Page>
  )
}
