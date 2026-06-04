// ESLint (flat config, ESLint 9) — P3-7.
//
// Świadomie WĄSKI zakres: tylko reguły `react-hooks`. To była realna luka (11
// martwych `eslint-disable-next-line react-hooks/exhaustive-deps`, których nic nie
// sprawdzało). Nie włączamy `@typescript-eslint/recommended` ani `js.recommended`,
// żeby nie zalać nigdy-nie-lintowanego kodu setkami nowych ostrzeżeń — to byłaby
// osobna, duża praca. `rules-of-hooks` = error (łapie realne bugi), `exhaustive-deps`
// = warn (nadaje sens istniejącym suppressom, ale nie wywraca builda).
//
// Uruchom: `npm run lint` (wymaga `npm install` — pakiety dodane do devDependencies).
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'out/**', 'node_modules/**', 'test/**', '*.config.*'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true }
      },
      globals: { ...globals.browser, ...globals.node }
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn'
    }
  }
]
