import clsx from 'clsx'
import { useBrand } from '../store/brandStore'

/**
 * Sidebar header. If the company has a logo uploaded, show it side-by-side
 * with the company name. Otherwise show the NautiCAI mark. The NautiCAI
 * brand still lives in the top-right of the topbar / reports.
 */
export default function Logo({ size = 36, withWordmark = true, className = '' }) {
  const brand = useBrand((s) => s.data)
  const logoSrc = useBrand((s) => s.logoSrc)
  const hasClient = brand.has_logo && !!logoSrc

  const src = hasClient ? logoSrc : '/logo.png'
  const name = hasClient ? brand.company_name : 'NautiCAI'
  const tag  = hasClient ? brand.company_tagline : 'Marine Intelligence'
  const accent = hasClient ? null : 'CAI'

  return (
    <div className={clsx('flex items-center gap-3', className)}>
      <div
        className="relative shrink-0 overflow-hidden rounded-xl ring-1 ring-white/10 shadow-glow bg-white/95 grid place-items-center"
        style={{ width: size, height: size }}>
        <img src={src} alt={name} className="h-full w-full object-contain p-1" draggable={false} />
      </div>
      {withWordmark && (
        <div className="leading-tight min-w-0">
          <div className="font-display text-base font-bold tracking-tight text-white truncate">
            {accent
              ? <>Nauti<span className="text-brand-400">{accent}</span></>
              : name}
          </div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 truncate">
            {tag || '\u00A0'}
          </div>
        </div>
      )}
    </div>
  )
}
