// M16: helpery marketplace'u pakietów — kodowanie pliku → base64 (import) i pobranie
// base64 → plik (eksport / „itch.io-style" bundle). Czyste utile (testowalne, bez DOM
// poza downloadBase64). Pakiety przesyłamy jako base64, bo REST jest JSON-owe.

/** Odczytaj wybrany plik `.caelopkg` jako base64 (bez prefiksu data-URI). */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result || '')
      resolve(result.includes(',') ? result.slice(result.indexOf(',') + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('read failed'))
    reader.readAsDataURL(file)
  })
}

/** Zamień base64 na bajty (do pobrania jako plik). */
export function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/** Pobierz bundle pakietu (base64) jako plik — eksport/udostępnianie (M16-4). */
export function downloadBase64(filename: string, b64: string): void {
  // base64ToBytes returns a freshly allocated Uint8Array, so its .buffer is a plain
  // ArrayBuffer (the cast narrows TS's ArrayBufferLike union for BlobPart).
  const blob = new Blob([base64ToBytes(b64).buffer as ArrayBuffer], {
    type: 'application/octet-stream'
  })
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
}

/** Tłumacz poziomu ryzyka pakietu na ton Badge (UI). */
export function riskTone(risk: string): 'success' | 'warn' | 'error' | 'neutral' {
  if (risk === 'high') return 'error'
  if (risk === 'medium') return 'warn'
  if (risk === 'low') return 'success'
  return 'neutral'
}

/** Czytelne podsumowanie zadeklarowanych uprawnień pakietu (karta zgody M16-2). */
export function permissionSummary(perm: {
  tools?: string[]
  starts_process?: boolean
  writes_files?: boolean
  network?: boolean
}): string[] {
  const out: string[] = []
  if (perm.starts_process) out.push('Runs a local process (MCP server)')
  if (perm.writes_files) out.push('Writes files into your project')
  if (perm.network) out.push('Accesses the network')
  if (perm.tools && perm.tools.length) out.push(`Uses tools: ${perm.tools.join(', ')}`)
  if (!out.length) out.push('Prompt/instructions only — no actions declared')
  return out
}
