import { Anchor, ShieldCheck, Sparkles, Camera } from 'lucide-react'

/** Shared two-column layout for /login and /register. The right panel shows
 *  the form (children). The left panel is the marine-themed hero. */
export default function AuthLayout({ title, subtitle, children }) {
  return (
    <div className="min-h-screen bg-ink-950 text-slate-100 flex">
      {/* Hero (hidden on mobile) */}
      <aside className="hidden lg:flex relative w-1/2 overflow-hidden bg-ocean-gradient">
        <div className="absolute inset-0 bg-wave-pattern opacity-20 mix-blend-screen pointer-events-none" />
        <div className="absolute inset-0 bg-gradient-to-br from-ink-950/30 via-ink-900/10 to-brand-900/40 pointer-events-none" />

        <div className="relative z-10 flex flex-col justify-between p-12 w-full">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-white/95 ring-1 ring-white/20 shadow-glow">
              <img src="/logo.png" className="h-9 w-9 object-contain" alt="NautiCAI" />
            </div>
            <div>
              <div className="font-display text-xl font-bold tracking-tight text-white">
                Nauti<span className="text-brand-300">CAI</span>
              </div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-brand-100/70">
                Marine Inspection · Automated
              </div>
            </div>
          </div>

          <div className="space-y-6 max-w-md">
            <h1 className="font-display text-4xl font-bold leading-tight">
              Inspection reports your<br />
              <span className="bg-gradient-to-r from-brand-200 to-accent-300 bg-clip-text text-transparent">
                divers actually want to file.
              </span>
            </h1>
            <p className="text-sm text-brand-100/80">
              Drop underwater photographs. We sort them by hull region, separate
              before-cleaning from after, identify fouling species and write the
              survey narrative for you — branded with your company logo, ready
              to send to the client.
            </p>

            <ul className="space-y-2.5 text-sm text-brand-100/90">
              <Bullet icon={Camera} text="Auto-routes photos into 11 hull zones" />
              <Bullet icon={Sparkles} text="Generates the Executive Summary sentences automatically" />
              <Bullet icon={ShieldCheck} text="Each company's data is fully isolated" />
              <Bullet icon={Anchor} text="Mirrors the Marine Service Report template you already use" />
            </ul>
          </div>

          <div className="text-[10px] uppercase tracking-[0.2em] text-brand-100/50">
            © {new Date().getFullYear()} NautiCAI · Built for diving companies
          </div>
        </div>
      </aside>

      {/* Form column */}
      <main className="flex-1 flex items-center justify-center p-6 md:p-10">
        <div className="w-full max-w-md glass-strong rounded-2xl p-8 shadow-xl">
          <div className="lg:hidden flex items-center gap-3 mb-6">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-white/95 ring-1 ring-white/20">
              <img src="/logo.png" className="h-7 w-7 object-contain" alt="NautiCAI" />
            </div>
            <div className="font-display text-lg font-bold text-white">
              Nauti<span className="text-brand-400">CAI</span>
            </div>
          </div>

          <h2 className="font-display text-2xl font-bold text-white">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </main>
    </div>
  )
}

function Bullet({ icon: Icon, text }) {
  return (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 grid h-6 w-6 place-items-center rounded-md bg-white/10 ring-1 ring-white/20">
        <Icon size={12} className="text-brand-100" />
      </span>
      <span>{text}</span>
    </li>
  )
}
