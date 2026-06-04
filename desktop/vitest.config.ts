// Vitest — testy jednostkowe czystych utili renderera (P3-9).
//
// Pliki testów leżą w `test/` (POZA zakresem tsconfig.web `src/renderer/**`),
// więc nie wpływają na `npm run typecheck`. Środowisko `node` — testowane funkcje
// są czyste (string/JSON), bez DOM.
//
// Uruchom: `npm test` (wymaga `npm install` — vitest dodany do devDependencies).
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    environment: 'node'
  }
})
