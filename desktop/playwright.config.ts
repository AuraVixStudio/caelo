import { defineConfig, devices } from '@playwright/test'

// E2E (P3-11) — sterują REALNĄ przeglądarką nad `preview:web` (Vite na :4599), gdzie
// `main.tsx` instaluje atrapę `window.caelo` (lib/devMock) → renderer działa BEZ Electrona
// i BEZ sidecara. Pokrywają powłokę: ładowanie, nawigację po modułach (rail), paletę Ctrl-K.
// (Przepływy z danymi backendu wymagają mocka REST — osobny krok; tu walidujemy shell.)
//
// Aktywacja: `npm install -D @playwright/test` + `npx playwright install chromium`, potem
// `npm run test:e2e`. NIE wpięte w `npm test` (Vitest) ani w `typecheck` — osobny tor.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://localhost:4599',
    trace: 'on-first-retry'
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // Vite serwer podglądu renderera (port wymuszony w vite.preview.config.ts).
  webServer: {
    command: 'npm run preview:web',
    url: 'http://localhost:4599',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000
  }
})
