import { resolve } from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Samodzielny serwer Vite dla samego renderera (bez Electrona) — wyłącznie do
// wizualnego podglądu UI w przeglądarce. Atrapę `window.caelo` instaluje main.tsx
// pod gałęzią DEV. Nie używany w buildzie/produkcji.
export default defineConfig({
  root: resolve(__dirname, 'src/renderer'),
  plugins: [react(), tailwindcss()],
  server: { port: 4599, strictPort: true }
})
