import { ArrowUpRight, ArrowDownRight } from 'lucide-react'
import clsx from 'clsx'
import { motion } from 'framer-motion'

export default function StatCard({ icon: Icon, label, value, delta, suffix = '', tone = 'brand' }) {
  const positive = (delta ?? 0) >= 0
  const tones = {
    brand:  'from-brand-400/30 to-brand-500/5 text-brand-200',
    warm:   'from-warning-500/30 to-warning-500/5 text-amber-200',
    danger: 'from-danger-500/30 to-danger-500/5 text-rose-200',
    success:'from-success-500/30 to-success-500/5 text-emerald-200',
  }
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass lift relative overflow-hidden rounded-2xl p-5"
    >
      <div className={clsx('absolute inset-0 bg-gradient-to-br opacity-40', tones[tone])} />
      <div className="relative">
        <div className="flex items-center justify-between">
          <div className="rounded-xl bg-white/5 p-2 ring-1 ring-white/10">
            <Icon size={18} className="text-brand-300" />
          </div>
          {delta !== undefined && (
            <div
              className={clsx(
                'flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold',
                positive ? 'bg-success-500/15 text-emerald-300' : 'bg-danger-500/15 text-rose-300',
              )}
            >
              {positive ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
              {Math.abs(delta)}%
            </div>
          )}
        </div>
        <div className="mt-4 text-3xl font-bold tracking-tight text-white">
          {value}
          <span className="text-base text-slate-400">{suffix}</span>
        </div>
        <div className="mt-1 text-xs uppercase tracking-wider text-slate-400">{label}</div>
      </div>
    </motion.div>
  )
}
