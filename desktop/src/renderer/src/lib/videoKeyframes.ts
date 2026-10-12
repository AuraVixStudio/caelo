// Klatki kluczowe xAI grok-imagine-video-1.5 (docs.x.ai „Video generation", 2026-10):
// `timestamp_s` leży na siatce 1/3 s, ściśle wewnątrz klipu, a klatki muszą być od
// siebie oddalone o co najmniej 1/3 s. Czyste funkcje → testowalne w Vitest (node env).

/** Wszystkie dozwolone momenty dla klipu o danej długości (w sekundach). */
export function keyframeTimes(duration: number): number[] {
  const steps = Math.max(0, Math.round(duration * 3) - 1)
  return Array.from({ length: steps }, (_, i) => (i + 1) / 3)
}

/** Etykieta momentu, np. 1.33s. */
export function formatKeyframeTime(seconds: number): string {
  return `${Number(seconds.toFixed(2))}s`
}

/** Moment dla nowej klatki: wolny punkt siatki najbliższy równemu podziałowi klipu. */
export function nextKeyframeTime(taken: number[], duration: number): number | null {
  const grid = keyframeTimes(duration)
  const used = new Set(taken.map((t) => Math.round(t * 3)))
  const free = grid.filter((t) => !used.has(Math.round(t * 3)))
  if (!free.length) return null
  const target = (duration * (taken.length + 1)) / (taken.length + 2)
  return free.reduce((best, t) => (Math.abs(t - target) < Math.abs(best - target) ? t : best))
}

/** Czy zestaw momentów jest poprawny dla długości klipu (siatka, wnętrze, unikalność). */
export function keyframesValid(times: number[], duration: number): boolean {
  const thirds = times.map((t) => Math.round(t * 3))
  if (thirds.some((q, i) => Math.abs(times[i] * 3 - q) > 1e-6)) return false
  if (thirds.some((q) => q <= 0 || q >= Math.round(duration * 3))) return false
  return new Set(thirds).size === thirds.length
}
