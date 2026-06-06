// Vitest — testy renderera: P3-9 (czyste utile) + P3-11 (komponenty React).
//
// Pliki testów leżą w `test/` (POZA zakresem tsconfig.web `src/renderer/**`),
// więc nie wpływają na `npm run typecheck`. Dwa rodzaje:
//   • `test/*.test.ts`            — czyste utile (string/JSON), środowisko `node` (domyślne).
//   • `test/components/*.test.tsx` — komponenty React + Testing Library; każdy plik ma na
//     górze docblock `// @vitest-environment jsdom` (DOM tylko tam, gdzie potrzebny — node
//     pozostaje domyślny, więc 122 testów utili jest nietknięte).
// Plugin React zapewnia automatyczny JSX runtime (komponenty nie importują `React`).
//
// Uruchom: `npm test` (wymaga `npm install`).
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    include: ['test/**/*.test.{ts,tsx}'],
    environment: 'node',
    // `globals: true` udostępnia afterEach globalnie → React Testing Library rejestruje
    // automatyczny `cleanup()` po każdym teście (inaczej kolejne render() kumulują się w
    // DOM i `getByRole` znajduje wiele elementów). Istniejące testy utili importują
    // describe/it/expect jawnie — z globals działają bez zmian.
    globals: true
  }
})
