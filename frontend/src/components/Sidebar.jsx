import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, FilePlus2, Images, BarChart3, FolderClosed, Settings, LifeBuoy, Sparkles,
  Users,
} from 'lucide-react'
import clsx from 'clsx'
import Logo from './Logo'

const NAV = [
  { to: '/',          icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/new',       icon: FilePlus2,       label: 'New Inspection' },
  { to: '/upload',    icon: Images,          label: 'Image Studio' },
  { to: '/analysis',  icon: BarChart3,       label: 'Analysis' },
  { to: '/reports',   icon: FolderClosed,    label: 'Reports' },
  { to: '/clients',   icon: Users,           label: 'Clients' },
  { to: '/settings',  icon: Settings,        label: 'Settings' },
]

export default function Sidebar() {
  return (
    <aside className="hidden lg:flex w-72 shrink-0 flex-col gap-6 border-r border-white/5 bg-ink-900/60 backdrop-blur-xl px-5 py-6">
      <div className="px-1">
        <Logo />
      </div>

      <div className="px-1">
        <NavLink to="/new" className="btn-primary w-full">
          <Sparkles size={16} />
          New Inspection
        </NavLink>
      </div>

      <nav className="flex flex-col gap-1">
        <div className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          Workspace
        </div>
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition',
                isActive
                  ? 'bg-white/[0.06] text-white border border-white/10'
                  : 'text-slate-300 hover:bg-white/5 hover:text-white border border-transparent',
              )
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={clsx(
                    'absolute left-0 top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-r-full bg-brand-400 transition-opacity',
                    isActive ? 'opacity-100' : 'opacity-0',
                  )}
                />
                <Icon size={18} className={clsx(isActive ? 'text-brand-300' : 'text-slate-400 group-hover:text-brand-300')} />
                <span>{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto">
        <div className="glass rounded-2xl p-4">
          <div className="flex items-center gap-2 text-brand-300">
            <LifeBuoy size={16} />
            <span className="text-xs font-semibold uppercase tracking-wider">Support</span>
          </div>
          <p className="mt-2 text-xs text-slate-400">
            Need help with a fouling assessment? Our marine engineers are on call 24/7.
          </p>
          <a
            href="mailto:support@nauticai-ai.com"
            className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-brand-300 hover:text-brand-200"
          >
            support@nauticai-ai.com →
          </a>
        </div>
      </div>
    </aside>
  )
}
