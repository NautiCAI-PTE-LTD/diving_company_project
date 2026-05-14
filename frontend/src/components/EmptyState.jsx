import { Inbox } from 'lucide-react'

export default function EmptyState({
  icon: Icon = Inbox,
  title = 'Nothing here yet',
  hint  = 'Upload images and create your first inspection.',
  action = null,
}) {
  return (
    <div className="grid place-items-center px-6 py-14 text-center">
      <div className="rounded-2xl bg-gradient-to-br from-brand-400/15 to-accent-500/5 p-4 ring-1 ring-brand-400/20">
        <Icon size={28} className="text-brand-300" />
      </div>
      <div className="mt-4 font-display text-base font-semibold text-white">{title}</div>
      <div className="mt-1 max-w-sm text-sm text-slate-400">{hint}</div>
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
