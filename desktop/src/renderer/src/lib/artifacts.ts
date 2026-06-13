// Faza-G/TOP5: renderowanie artefaktów modelu (HTML/SVG) w SANDBOXOWANYM iframe.
// Bezpieczeństwo (defense-in-depth):
//  • iframe `sandbox="allow-scripts"` BEZ `allow-same-origin` → opaque origin: brak dostępu
//    do okna rodzica, tokenu sesji, localStorage/cookies aplikacji.
//  • wstrzyknięty <meta CSP> — przecina się z (i tak restrykcyjnym) CSP rodzica dziedziczonym
//    przez srcdoc: inline script/style działają, ale `connect-src`/skrypty zewnętrzne są
//    zablokowane → artefakt nie sięgnie sieci ani backendu na pętli zwrotnej.
//  • brak allow-forms/allow-popups/allow-top-navigation → nie wyśle formularza, nie otworzy
//    okna, nie znawiguje ramki aplikacji.
// Mermaid: ODŁOŻONY — CSP blokuje skrypt z CDN (a <meta> nie może poluzować dziedziczonego
// CSP), a bundlowanie wymaga `npm install mermaid` (sync lockfile = zadanie usera).

export const ARTIFACT_LANGS = ['html', 'svg'] as const
export type ArtifactLang = (typeof ARTIFACT_LANGS)[number]

export function isArtifactLang(lang: string): lang is ArtifactLang {
  return (ARTIFACT_LANGS as readonly string[]).includes(lang)
}

// default-src 'none' ⇒ connect/frame/object zablokowane; jawnie tylko inline script/style + media.
const IFRAME_CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; " +
  'img-src data: blob: https:; media-src data: blob: https:; font-src data:'

const CSP_META = `<meta http-equiv="Content-Security-Policy" content="${IFRAME_CSP}">`

// Skrypt raportujący wysokość treści do rodzica (auto-resize). Cross-origin postMessage
// (opaque origin) → targetOrigin '*'; rodzic weryfikuje event.source === iframe.contentWindow.
const RESIZE_SCRIPT =
  '<script>(function(){function p(){try{parent.postMessage(' +
  '{__caeloArtifactHeight:document.documentElement.scrollHeight},"*")}catch(e){}}' +
  'if(window.ResizeObserver)new ResizeObserver(p).observe(document.documentElement);' +
  'window.addEventListener("load",p);setTimeout(p,50);setTimeout(p,400);})();<\/script>'

const BASE_STYLE =
  '<style>html,body{margin:0;padding:0;background:#fff;color:#111;' +
  'font-family:system-ui,-apple-system,sans-serif}body{padding:8px}' +
  'svg,img,canvas{max-width:100%;height:auto}</style>'

function buildHtml(code: string): string {
  let out = code
  // Wstrzyknij CSP jak najwcześniej: do <head>, inaczej tuż za <html>, inaczej na początek.
  // Replacer-funkcja (nie string) — unika interpretacji `$` w treści.
  if (/<head[^>]*>/i.test(out)) out = out.replace(/<head[^>]*>/i, (m) => m + CSP_META + BASE_STYLE)
  else if (/<html[^>]*>/i.test(out))
    out = out.replace(/<html[^>]*>/i, (m) => `${m}<head>${CSP_META}${BASE_STYLE}</head>`)
  else out = `${CSP_META}${BASE_STYLE}${out}`
  // Skrypt resize na końcu <body> (lub na końcu dokumentu).
  if (/<\/body>/i.test(out)) out = out.replace(/<\/body>/i, () => RESIZE_SCRIPT + '</body>')
  else out = out + RESIZE_SCRIPT
  return out
}

function wrapSvg(code: string): string {
  return (
    `<!doctype html><html><head><meta charset="utf-8">${CSP_META}${BASE_STYLE}</head>` +
    `<body>${code}${RESIZE_SCRIPT}</body></html>`
  )
}

/** Zbuduj `srcdoc` sandboxowanego iframe dla artefaktu danego typu. */
export function buildArtifactSrcDoc(lang: ArtifactLang, code: string): string {
  return lang === 'svg' ? wrapSvg(code) : buildHtml(code)
}
