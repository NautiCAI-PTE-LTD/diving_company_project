import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bell, Search, ChevronDown, CircleUser, LogOut, Settings as Cog,
  Building2, Cpu, Zap,
} from 'lucide-react'
import toast from 'react-hot-toast'
import Logo from './Logo'
import { useAuth } from '../store/authStore'
import { useBrand } from '../store/brandStore'
import { api } from '../lib/api'

export default function Topbar() {
  const nav = useNavigate()
  const user    = useAuth((s) => s.user)
  const logout  = useAuth((s) => s.logout)
  const brand   = useBrand((s) => s.data)
  const resetBrand = useBrand((s) => s.reset)
  const [open, setOpen] = useState(false)
  const [sys, setSys] = useState(null)
  const menuRef = useRef(null)

  useEffect(() => {
    function onClick(e) { if (!menuRef.current?.contains(e.target)) setOpen(false) }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [])

  // Poll system status until models are warm; then back off to 30s for fresh GPU mem reading.
  useEffect(() => {
    let timer
    const tick = async () => {
      try {
        const { data } = await api.get('/system')
        setSys(data)
        const delay = data?.warmup === 'ready' ? 30000 : 2500
        timer = setTimeout(tick, delay)
      } catch {
        timer = setTimeout(tick, 10000)
      }
    }
    tick()
    return () => clearTimeout(timer)
  }, [])

  const onLogout = () => {
    logout(); resetBrand()
    toast.success('Signed out')
    nav('/login', { replace: true })
  }

  const initials = (user?.full_name || user?.email || 'U')
    .split(/[ @]/).map((s) => s[0]).slice(0, 2).join('').toUpperCase()

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b border-white/5 bg-ink-950/70 px-4 sm:px-6 backdrop-blur-xl">
      <div className="lg:hidden">
        <Logo size={32} withWordmark={false} />
      </div>

      <div className="relative flex-1 max-w-xl">
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="search"
          placeholder="Search vessels, jobs, reports…"
          className="w-full rounded-xl border border-white/10 bg-white/[0.04] pl-9 pr-3 py-2.5 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-brand-400/40"
        />
      </div>

      <div className="ml-auto flex items-center gap-2">
        {sys && (
          <div
            title={sys.device === 'cuda'
              ? `${sys.gpu_name || 'CUDA GPU'} · models ${sys.warmup}`
              : `CPU inference · models ${sys.warmup}`}
            className={`hidden md:flex items-center gap-1.5 rounded-lg ring-1 px-2 py-1.5 ${
              sys.device === 'cuda'
                ? 'bg-emerald-500/10 ring-emerald-400/30 text-emerald-200'
                : 'bg-white/[0.04] ring-white/10 text-slate-300'
            }`}
          >
            {sys.device === 'cuda' ? <Zap size={12} /> : <Cpu size={12} />}
            <span className="text-[11px] font-semibold">
              {sys.device === 'cuda' ? 'GPU' : 'CPU'}
            </span>
            {sys.warmup !== 'ready' && (
              <span className="h-1.5 w-1.5 rounded-full bg-amber-300 animate-pulse" />
            )}
          </div>
        )}
        {brand?.company_name && (
          <div className="hidden md:flex items-center gap-1.5 rounded-lg bg-white/[0.04] ring-1 ring-white/10 px-2 py-1.5">
            <Building2 size={12} className="text-brand-300" />
            <span className="text-[11px] font-semibold text-slate-300 truncate max-w-[140px]">
              {brand.company_name}
            </span>
          </div>
        )}

        <button className="btn-ghost !px-2.5 !py-2 relative" title="Notifications">
          <Bell size={16} />
          <span className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-brand-400 ring-2 ring-ink-950" />
        </button>

        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] hover:bg-white/[0.06] px-2.5 py-1.5 transition">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-400 to-accent-500 text-ink-950 font-bold text-xs">
              {initials}
            </div>
            <div className="leading-tight pr-1 hidden sm:block text-left">
              <div className="text-sm font-semibold text-white truncate max-w-[140px]">
                {user?.full_name || user?.email || 'User'}
              </div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400">
                {user?.role || 'member'}
              </div>
            </div>
            <ChevronDown size={14} className="text-slate-400" />
          </button>

          {open && (
            <div className="absolute right-0 top-12 w-60 glass-strong rounded-xl p-2 shadow-xl">
              <div className="px-3 py-2 border-b border-white/5">
                <div className="text-sm font-semibold text-white truncate">{user?.full_name || '—'}</div>
                <div className="text-[11px] text-slate-400 truncate">{user?.email}</div>
              </div>
              <button onClick={() => { setOpen(false); nav('/settings') }}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-200 hover:bg-white/5">
                <Cog size={14} className="text-brand-300" /> Workspace Settings
              </button>
              <button onClick={onLogout}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-rose-300 hover:bg-rose-500/10">
                <LogOut size={14} /> Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
