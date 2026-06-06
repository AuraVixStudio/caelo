// Stub `window.matchMedia` for jsdom (which does not implement it).
//
// MUST be imported BEFORE any module that reads matchMedia at IMPORT time — notably
// `lib/theme`, whose module-load code calls `systemPrefersDark()`. ES modules evaluate
// imported modules in source order, so `import './_matchMedia'` placed first guarantees
// the stub is installed before the theme module runs.
//
// Not a `*.test.ts(x)` file → Vitest does not collect it as a suite.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia
}
