# Caelo — brand assets

Logo: five rays (Chat · Image · Video · Voice · Code) radiating from one star — "every mode under one sky."

## Files
- `icon-color-dark.svg` / `icon-color-light.svg` — app icon (rounded tile, transparent corners)
- `mark-color.svg`, `mark-mono-black.svg`, `mark-mono-white.svg` — bare mark (transparent)
- `lockup-horizontal-onlight|ondark.svg`, `lockup-vertical-onlight|ondark.svg` — mark + wordmark
- `wordmark-onlight.svg` — "Caelo" only
- `og-banner.svg` / `og-banner.png` (1280×640) — social / GitHub OG image
- `favicon.svg`
- `icons/` — `icon-16…1024.png`, `favicon-16/32/48.png`, `icon.ico` (Windows), `icon.icns` (macOS)

## electron-builder
- Windows: `build/icon.ico`  (use `icons/icon.ico`)
- macOS:   `build/icon.icns` (use `icons/icon.icns`)
- Linux:   `build/icon.png`  (use `icons/icon-512.png` or `icon-1024.png`)

## Palette
Sky gradient: #4338CA → #7C3AED → #38BDF8 · Night tile: #1E2150 → #0B1020 · Ink: #0F172A
Ray colours (left→right): #6366F1 #8B5CF6 #A855F7 #3B82F6 #38BDF8

## Type
Wordmark set in Inter (Bold). For production, outline the wordmark to paths so it doesn't depend on installed fonts (Inkscape: Path ▸ Object to Path; Illustrator: Type ▸ Create Outlines).

## Name / trademark notes
- Use "Caelo" alone — NOT "Caelo Software" (collides with an existing company + reads oddly with software).
- "works with xAI / for Grok" is fine as a tagline (nominative use), never inside the product name.
- Verify free GitHub org / npm / PyPI / domain (.dev/.ai) + a quick USPTO/EUIPO check before committing.
