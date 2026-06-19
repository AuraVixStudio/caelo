// @vitest-environment jsdom
// Regresja (D1, live): zapis w sekcji Voice na DOLE długiej strony Settings dawał
// potwierdzenie w bannerze na GÓRZE strony (poza widokiem) → user nie widział feedbacku.
// Po fixie potwierdzenia/błędy idą w toast (fixed bottom-right, role=status), niezależnie
// od pozycji scrolla, a statycznego bannera już nie ma.
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// vi.mock jest hoistowany ponad importy — mock fn + STABILNE wyniki hooków muszą
// powstać w vi.hoisted. Stabilne referencje są krytyczne: prawdziwe useModels/useSettings
// zwracają cache'owane obiekty; gdyby mock tworzył nowy obiekt na render, useEffect
// w Settings ([modelsResp]) zapętliłby się w nieskończoność (OOM).
const { saveSettings, modelsRes, settingsRes, authRes } = vi.hoisted(() => ({
  saveSettings: vi.fn().mockResolvedValue({}),
  modelsRes: {
    models: { chat: ['grok-4'], code: ['grok-4'], voices: ['eve', 'ara'], default_voice: 'eve' },
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

function renderSettings(): void {
  render(
    <ToastProvider>
      <Settings conn={conn} />
    </ToastProvider>
  )
}

describe('Settings — feedback zapisu przez toast (D1 regresja)', () => {
  it('zapis Voice pokazuje toast role=status, nie statyczny banner', async () => {
    renderSettings()
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
