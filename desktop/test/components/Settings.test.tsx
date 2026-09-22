// @vitest-environment jsdom
// Podkarty dostawców: xAI / Google / OpenAI / General — logowanie każdego dostawcy
// ma własną zakładkę zamiast jednej długiej listy kart.
// Regresja (D1, live): zapis w sekcji Voice na DOLE długiej strony Settings dawał
// potwierdzenie w bannerze na GÓRZE strony (poza widokiem) → user nie widział feedbacku.
// Po fixie potwierdzenia/błędy idą w toast (fixed bottom-right, role=status), niezależnie
// od pozycji scrolla, a statycznego bannera już nie ma.
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// vi.mock jest hoistowany ponad importy — mock fn + STABILNE wyniki hooków muszą
// powstać w vi.hoisted. Stabilne referencje są krytyczne: prawdziwe useModels/useSettings
// zwracają cache'owane obiekty; gdyby mock tworzył nowy obiekt na render, useEffect
// w Settings ([modelsResp]) zapętliłby się w nieskończoność (OOM).
const { saveSettings, modelsRes, settingsRes, authRes } = vi.hoisted(() => ({
  saveSettings: vi.fn().mockResolvedValue({}),
  modelsRes: {
    models: {
      chat: ['grok-4'],
      code: ['grok-4'],
      voices: ['eve', 'ara'],
      default_voice: 'eve',
      default_chat: 'grok-4',
      default_code: 'grok-4',
      items: [
        { id: 'grok-4', provider: 'xai', media_type: 'chat', is_default: true,
          capabilities: { supports_tools: true } },
        { id: 'gemini-3.7-flash', provider: 'google', media_type: 'chat', is_default: true,
          capabilities: { supports_tools: true } },
        { id: 'gpt-5.6-luna', provider: 'openai', media_type: 'chat', is_default: true,
          capabilities: { supports_tools: true } },
        { id: 'gemini-3.1-flash-image', provider: 'google', media_type: 'image',
          is_default: true, capabilities: { supports_tools: false } }
      ]
    },
    error: null,
    loading: false
  },
  settingsRes: {
    settings: { chat_model: 'grok-4', code_model: 'grok-4', voice: 'eve', voice_language: 'en' },
    error: null,
    loading: false
  },
  authRes: {
    auth: { auth_source: 'auto', active_source: 'none', has_api_key: false },
    error: null,
    loading: false
  }
}))

vi.mock('../../src/renderer/src/lib/serverState', () => ({
  useModels: () => modelsRes,
  useSettings: () => settingsRes,
  useAuthStatus: () => authRes,
  refreshAuth: vi.fn().mockResolvedValue(undefined),
  saveSettings
}))

vi.mock('../../src/renderer/src/lib/theme', () => ({
  useTheme: () => ({ theme: 'system', setTheme: vi.fn() })
}))

vi.mock('../../src/renderer/src/lib/api', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  getOutputDir: vi.fn().mockResolvedValue({ path: '' }),
  login: vi.fn(),
  logout: vi.fn(),
  clearApiKey: vi.fn(),
  setOutputDir: vi.fn()
}))

import { Settings } from '../../src/renderer/src/components/Settings'
import { ToastProvider } from '../../src/renderer/src/components/ui/Toast'

const conn = { baseUrl: '', token: '' } as never

async function renderSettings(): Promise<void> {
  await act(async () => {
    render(
      <ToastProvider>
        <Settings conn={conn} />
      </ToastProvider>
    )
    await Promise.resolve()
  })
}

describe('Settings', () => {
  // Aktywna podkarta jest zapamiętywana w localStorage — każdy test startuje od xAI.
  beforeEach(() => localStorage.clear())

  it('dzieli dostawców na podkarty — domyślnie xAI, reszta ukryta', async () => {
    await renderSettings()

    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'xAI / Grok',
      'Google',
      'OpenAI',
      'General'
    ])
    expect(screen.getByRole('tab', { name: 'xAI / Grok' })).toHaveAttribute('aria-selected', 'true')

    // Karta xAI: źródło modelu, logowanie i klucz — bez kart innych dostawców.
    expect(screen.getAllByRole('heading').map((heading) => heading.textContent)).toEqual([
      'Settings',
      'Privacy and credentials',
      'Model source',
      'xAI Account (SuperGrok / X Premium+)',
      'xAI API Key',
      'Voice'
    ])
  })

  it('przełączenie podkarty pokazuje logowanie tylko tego dostawcy', async () => {
    await renderSettings()

    await userEvent.click(screen.getByRole('tab', { name: 'Google' }))
    expect(screen.getByRole('heading', { name: 'Google Gemini / Vertex AI' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'xAI API Key' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'OpenAI API' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'OpenAI' }))
    expect(screen.getByRole('heading', { name: 'OpenAI API' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Google Gemini / Vertex AI' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'General' }))
    expect(screen.getByRole('heading', { name: 'Default Models' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Generation Output Folder' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Appearance' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'OpenAI API' })).not.toBeInTheDocument()
  })

  it('domyślne modele wymieniają wszystkich dostawców i zapisują dostawcę wybranego modelu', async () => {
    await renderSettings()
    await userEvent.click(screen.getByRole('tab', { name: 'General' }))

    const chat = screen.getByLabelText('Default chat model') as HTMLSelectElement
    expect([...chat.querySelectorAll('optgroup')].map((group) => group.label)).toEqual([
      'xAI',
      'Google Gemini',
      'OpenAI'
    ])
    expect([...chat.options].map((option) => option.value)).toEqual([
      'grok-4',
      'gemini-3.7-flash',
      'gpt-5.6-luna'
    ])
    // Modele obrazu nie są modelami czatu — nie mogą trafić na listę.
    expect([...chat.options].map((option) => option.value)).not.toContain('gemini-3.1-flash-image')

    await userEvent.selectOptions(chat, 'gemini-3.7-flash')
    await userEvent.click(
      within(screen.getByRole('heading', { name: 'Default Models' }).parentElement as HTMLElement)
        .getByRole('button', { name: 'Save' })
    )

    // Sam model nie mówi, czyj jest — bez `chat_provider` Chat wróciłby do xAI.
    expect(saveSettings).toHaveBeenCalledWith(conn, {
      chat_model: 'gemini-3.7-flash',
      code_model: 'grok-4',
      chat_provider: 'google',
      code_provider: 'xai'
    })
  })

  it('zapis Voice pokazuje toast role=status, nie statyczny banner', async () => {
    await renderSettings()
    // Brak statycznego bannera potwierdzenia przed jakąkolwiek akcją.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    // Klik "Save" wewnątrz karty Voice (h2 "Voice" → kontener karty).
    const voiceCard = screen.getByRole('heading', { name: 'Voice' }).parentElement as HTMLElement
    await userEvent.click(within(voiceCard).getByRole('button', { name: 'Save' }))

    expect(saveSettings).toHaveBeenCalledWith(conn, { voice: 'eve', voice_language: 'en' })
    // Potwierdzenie dociera kanałem toast (widoczne niezależnie od scrolla).
    const toast = await screen.findByRole('status')
    expect(toast).toHaveTextContent('Voice preferences saved.')
  })
})
