import clsx from 'clsx'
import { Check } from 'lucide-react'

export default function Stepper({ steps, current, onJump }) {
  return (
    <ol className="flex w-full items-center gap-2 sm:gap-4">
      {steps.map((s, i) => {
        const status = i < current ? 'done' : i === current ? 'active' : 'todo'
        return (
          <li key={s.id} className="flex flex-1 items-center">
            <button
              type="button"
              onClick={() => onJump?.(i)}
              className={clsx(
                'group flex flex-1 items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition',
                status === 'active' && 'border-brand-400/50 bg-brand-400/10 shadow-glow',
                status === 'done'   && 'border-success-500/40 bg-success-500/5',
                status === 'todo'   && 'border-white/10 bg-white/[0.03] hover:border-white/20',
              )}
            >
              <div
                className={clsx(
                  'flex h-8 w-8 items-center justify-center rounded-lg text-sm font-semibold ring-1',
                  status === 'active' && 'bg-brand-400 text-ink-950 ring-brand-400/30',
                  status === 'done'   && 'bg-success-500 text-ink-950 ring-success-500/30',
                  status === 'todo'   && 'bg-white/10 text-slate-300 ring-white/10',
                )}
              >
                {status === 'done' ? <Check size={16} strokeWidth={3} /> : i + 1}
              </div>
              <div className="min-w-0">
                <div className={clsx('text-[10px] uppercase tracking-wider',
                  status === 'active' ? 'text-brand-300' : 'text-slate-400')}>
                  Step {i + 1}
                </div>
                <div className="truncate text-sm font-semibold text-white">{s.title}</div>
              </div>
            </button>
            {i < steps.length - 1 && (
              <div className="hidden sm:block mx-2 h-px flex-1 bg-gradient-to-r from-white/15 to-transparent" />
            )}
          </li>
        )
      })}
    </ol>
  )
}
