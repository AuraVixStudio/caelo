import type { Page, Route } from '@playwright/test'

// Mock lokalnego backendu (devMock ustawia baseUrl http://127.0.0.1:9) — pozwala E2E
// walidować PRZEPŁYWY Z DANYMI bez Electrona/sidecara. Przechwytuje WSZYSTKIE żądania
// do backendu i odpowiada JSON-em per ścieżka; testy nadpisują wybrane ścieżki handlerem
// (handler zwraca obiekt → fulfill 200 JSON; albo sam woła `route` i zwraca undefined).
// Assety Vite (localhost:4599) NIE są ruszane (inny origin).
export async function mockBackend(
  page: Page,
  handlers: Record<string, (route: Route, url: URL) => unknown | Promise<unknown>> = {}
): Promise<void> {
  const defaults: Record<string, unknown> = {
    '/projects': { projects: [], recent_workspaces: [], current_project_id: null },
    '/commands': { commands: [] },
    '/history': { events: [] },
    '/artifacts': { artifacts: [] },
    '/settings': {
      chat_model: 'grok-4',
      code_model: 'grok-4',
      chat_effort: '',
      code_effort: '',
      has_api_key: true
    },
    '/models': { chat: ['grok-4'], code: ['grok-4'], default_chat: 'grok-4', default_code: 'grok-4' }
  }
  await page.route('http://127.0.0.1:9/**', async (route) => {
    const url = new URL(route.request().url())
    const handler = handlers[url.pathname]
    if (handler) {
      const body = await handler(route, url)
      if (body === undefined) return // handler już obsłużył route (fulfill/abort)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
      return
    }
    const def = defaults[url.pathname] ?? {}
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(def) })
  })
}
