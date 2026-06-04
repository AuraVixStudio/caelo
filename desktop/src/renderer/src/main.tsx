import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ThemeProvider } from './lib/theme'
import './index.css'

async function boot(): Promise<void> {
  // Podgląd UI w przeglądarce (bez Electrona): podstaw atrapę mostka. Tylko DEV.
  if (import.meta.env.DEV && !window.grok) {
    const { installBrowserMock } = await import('./lib/devMock')
    installBrowserMock()
  }

  const container = document.getElementById('root')
  if (!container) throw new Error('Root element #root not found')

  createRoot(container).render(
    <React.StrictMode>
      <ThemeProvider>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </ThemeProvider>
    </React.StrictMode>
  )
}

void boot()
