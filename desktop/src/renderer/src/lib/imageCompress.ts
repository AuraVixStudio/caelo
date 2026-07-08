// Kompresja obrazów wejściowych po stronie renderera (media: referencje obrazu,
// kadr startowy wideo). Backend odrzuca data-URI > MAX_IMAGE_URI (patrz
// caelo_core/validation.py) — zamiast błędu przekształcamy zbyt duży obraz do
// WebP z malejącą jakością i (w razie potrzeby) wymiarami, aż zmieści się w limicie.

import { fileToDataUri } from './files'

// Mirror caelo_core/validation.py -> MAX_IMAGE_URI (długość data-URI w znakach).
export const MAX_IMAGE_URI_CHARS = 12 * 1024 * 1024

export interface CompressResult {
  uri: string // data-URI (oryginał lub przekompresowany)
  compressed: boolean // czy obraz został przekształcony
  fitsBudget: boolean // czy zmieścił się w limicie (może być false, gdy nie da się bardziej ścisnąć)
  originalChars: number
  finalChars: number
}

function loadImage(uri: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new window.Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('image decode failed'))
    img.src = uri
  })
}

// Zjazd jakości przy danym rozmiarze, potem zmniejszamy wymiary.
const QUALITY_LADDER = [0.85, 0.7, 0.55, 0.4]
const SCALE_STEP = 0.8
const MIN_DIMENSION = 64
const MAX_STEPS = 12

/**
 * Zwraca data-URI pliku, kompresując go do WebP tylko gdy oryginał przekracza
 * `maxChars`. Obrazy w limicie przechodzą bez zmian (zachowują oryginalny format).
 * Gdy Canvas/WebP jest niedostępny (np. środowisko testowe), zwraca oryginał.
 */
export async function compressImageIfNeeded(
  file: File,
  maxChars: number = MAX_IMAGE_URI_CHARS
): Promise<CompressResult> {
  const original = await fileToDataUri(file)
  const originalChars = original.length
  if (originalChars <= maxChars) {
    return { uri: original, compressed: false, fitsBudget: true, originalChars, finalChars: originalChars }
  }

  // Zostaw margines na inflację base64 / overhead nagłówka.
  const budget = Math.floor(maxChars * 0.95)

  let img: HTMLImageElement
  let ctx: CanvasRenderingContext2D | null
  let canvas: HTMLCanvasElement
  try {
    img = await loadImage(original)
    canvas = document.createElement('canvas')
    ctx = canvas.getContext('2d')
  } catch {
    return { uri: original, compressed: false, fitsBudget: false, originalChars, finalChars: originalChars }
  }
  if (!ctx) {
    return { uri: original, compressed: false, fitsBudget: false, originalChars, finalChars: originalChars }
  }

  let width = img.naturalWidth || img.width
  let height = img.naturalHeight || img.height
  if (!width || !height) {
    return { uri: original, compressed: false, fitsBudget: false, originalChars, finalChars: originalChars }
  }

  let best = original // najlepszy (najmniejszy) kandydat, gdyby nic nie zmieściło się w budżecie

  for (let step = 0; step < MAX_STEPS; step++) {
    canvas.width = Math.max(1, Math.round(width))
    canvas.height = Math.max(1, Math.round(height))
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)

    for (const q of QUALITY_LADDER) {
      const webp = canvas.toDataURL('image/webp', q)
      // Gdy WebP nie jest wspierany, przeglądarka zwraca image/png — użyj wtedy JPEG.
      const out = webp.startsWith('data:image/webp') ? webp : canvas.toDataURL('image/jpeg', q)
      if (out.length <= budget) {
        return { uri: out, compressed: true, fitsBudget: true, originalChars, finalChars: out.length }
      }
      if (out.length < best.length) best = out
    }

    width *= SCALE_STEP
    height *= SCALE_STEP
    if (width < MIN_DIMENSION || height < MIN_DIMENSION) break
  }

  // Nie udało się zejść pod budżet — zwróć najmniejszy uzyskany wariant (i tak lepszy niż oryginał).
  return {
    uri: best,
    compressed: best !== original,
    fitsBudget: best.length <= budget,
    originalChars,
    finalChars: best.length
  }
}
