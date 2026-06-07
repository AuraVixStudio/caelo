// Caelo brand mark — five rays (Chat · Image · Video · Voice · Code) radiating from
// one star: "every mode under one sky". Inlined as SVG (not loaded from /public) so it
// renders crisply at any size, needs no network/CSP allowance, and the star colour can
// adapt per variant. Canonical source: assets/brand/ (mark-color.svg / favicon.svg).
import { cn } from '../../lib/cn'

/** The bare mark: colour rays + a star. `transparent` background — drop it on any
 *  surface. `starColor` defaults to the brand purple (legible on light & dark). */
function Rays({ starColor = '#7C3AED' }: { starColor?: string }) {
  return (
    <g>
      <line x1="-18" y1="-26" x2="-56" y2="44" stroke="#6366F1" strokeWidth="5.5" strokeLinecap="round" />
      <line x1="-9" y1="-30" x2="-29" y2="48" stroke="#8B5CF6" strokeWidth="5.5" strokeLinecap="round" />
      <line x1="0" y1="-32" x2="0" y2="50" stroke="#A855F7" strokeWidth="5.5" strokeLinecap="round" />
      <line x1="9" y1="-30" x2="29" y2="48" stroke="#3B82F6" strokeWidth="5.5" strokeLinecap="round" />
      <line x1="18" y1="-26" x2="56" y2="44" stroke="#38BDF8" strokeWidth="5.5" strokeLinecap="round" />
      <path
        d="M0 -11 C0 -4 -4 0 -11 0 C-4 0 0 4 0 11 C0 4 4 0 11 0 C4 0 0 -4 0 -11 Z"
        transform="translate(0 -46)"
        fill={starColor}
      />
    </g>
  )
}

export interface BrandMarkProps {
  /** Pixel size of the (square) mark. */
  size?: number
  className?: string
  /** Star colour for the bare mark (ignored by the tile, which uses white). */
  starColor?: string
}

/** Bare Caelo mark (transparent background) — use on coloured/surface backgrounds. */
export function BrandMark({ size = 32, className, starColor }: BrandMarkProps) {
  return (
    <svg
      viewBox="-70 -70 140 140"
      width={size}
      height={size}
      className={cn('shrink-0', className)}
      role="img"
      aria-label="Caelo"
    >
      <Rays starColor={starColor} />
    </svg>
  )
}

/** Horizontal lockup: mark + "Caelo" wordmark. Transparent background; the "aelo"
 *  letters use `currentColor` (set a text colour on the parent — defaults to `text-fg`)
 *  so the same component reads correctly on light AND dark, unlike the static
 *  on-light / on-dark SVGs. Aspect ratio is fixed (460×150); pass a `height`. */
export function BrandLockup({ height = 40, className }: { height?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 460 150"
      width={(460 / 150) * height}
      height={height}
      className={cn('shrink-0 text-fg', className)}
      role="img"
      aria-label="Caelo"
    >
      <defs>
        <linearGradient id="caelo-sky" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4338CA" />
          <stop offset="0.5" stopColor="#7C3AED" />
          <stop offset="1" stopColor="#38BDF8" />
        </linearGradient>
      </defs>
      <g transform="translate(75 75) scale(0.4571)">
        <Rays starColor="#7C3AED" />
      </g>
      <text
        x="150"
        y="93"
        fontFamily="Inter,'Segoe UI',Helvetica,Arial,sans-serif"
        fontSize="62"
        fontWeight="700"
        letterSpacing="0.5"
      >
        <tspan fill="url(#caelo-sky)">C</tspan>
        <tspan fill="currentColor">aelo</tspan>
      </text>
    </svg>
  )
}

/** Caelo app-icon tile — rays + white star on the brand "night" radial, rounded
 *  corners. Self-contained (own background), so it looks identical in light & dark. */
export function BrandTile({ size = 32, className }: BrandMarkProps) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={cn('shrink-0', className)}
      role="img"
      aria-label="Caelo"
    >
      <defs>
        <radialGradient id="caelo-night" cx="0.3" cy="0.25" r="0.95">
          <stop offset="0" stopColor="#1E2150" />
          <stop offset="1" stopColor="#0B1020" />
        </radialGradient>
      </defs>
      <rect x="0" y="0" width="64" height="64" rx="14.4" fill="url(#caelo-night)" />
      <g transform="translate(32 32) scale(0.2743)">
        <Rays starColor="#FFFFFF" />
      </g>
    </svg>
  )
}
