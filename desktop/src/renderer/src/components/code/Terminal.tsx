import { useEffect, useRef } from 'react'
import { Terminal as XTerm } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import type { Conn } from '../../lib/api'
import { useTheme } from '../../lib/theme'

export function Terminal({ conn }: { conn: Conn }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const { resolved } = useTheme()

  useEffect(() => {
    if (!ref.current) return
    const term = new XTerm({
      fontSize: 12,
      fontFamily: "'JetBrains Mono', Consolas, monospace",
      convertEol: true,
      cursorBlink: true,
      theme:
        resolved === 'dark'
          ? { background: '#0e0e10', foreground: '#f4f4f5', cursor: '#d7dde5' }
          : { background: '#ffffff', foreground: '#18181b', cursor: '#2b323b' }
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(ref.current)
    try {
      fit.fit()
    } catch {
      /* ignore */
    }

    let cleanup = false
    const ws = new WebSocket(
      conn.baseUrl.replace(/^http/, 'ws') + '/terminal?token=' + encodeURIComponent(conn.token)
    )
    ws.onmessage = (ev) => {
      let m: { type?: string; data?: string; error?: string }
      try {
        m = JSON.parse(ev.data as string)
      } catch {
        return
      }
      if (m.type === 'output') term.write(m.data ?? '')
      else if (m.type === 'error') term.write(`\r\n\x1b[31m[${m.error}]\x1b[0m\r\n`)
      else if (m.type === 'exit') term.write('\r\n[process exited]\r\n')
    }
    // P1-5: pokaż rozłączenie (np. po restarcie sidecara); efekt i tak wstaje na nowo,
    // bo jest kluczowany na [conn.baseUrl, conn.token].
    ws.onclose = () => {
      if (!cleanup) term.write('\r\n\x1b[33m[terminal disconnected]\x1b[0m\r\n')
    }
    ws.onerror = () => {
      try {
        ws.close()
      } catch {
        /* ignore */
      }
    }
    const disp = term.onData((d) => {
      try {
        ws.send(JSON.stringify({ type: 'input', data: d }))
      } catch {
        /* ignore */
      }
    })

    const onResize = (): void => {
      try {
        fit.fit()
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      } catch {
        /* ignore */
      }
    }
    window.addEventListener('resize', onResize)

    return () => {
      cleanup = true
      window.removeEventListener('resize', onResize)
      disp.dispose()
      try {
        ws.close()
      } catch {
        /* ignore */
      }
      term.dispose()
    }
    // odtwórz terminal po zmianie połączenia (np. restart sidecara → nowy port/token)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conn.baseUrl, conn.token])

  return <div className="h-full w-full p-2" ref={ref} />
}
