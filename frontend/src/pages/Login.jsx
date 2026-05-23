import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Mail, Lock, Loader2, ArrowRight, Anchor } from 'lucide-react'
import toast from 'react-hot-toast'
import { login } from '../lib/api'
import { useAuth } from '../store/authStore'
import { useBrand } from '../store/brandStore'
import AuthLayout from '../components/AuthLayout'

export default function Login() {
  const setSession = useAuth((s) => s.setSession)
  const refreshBrand = useBrand((s) => s.refresh)

  const [form, setForm] = useState({ email: '', password: '' })
  const [busy, setBusy] = useState(false)
  const onSet = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    if (!form.email || !form.password) {
      toast.error('Email and password are required'); return
    }
    setBusy(true)
    try {
      const r = await login(form)
      setSession({ token: r.access_token, user: r.user, company: r.company })
      await refreshBrand()
      toast.success(`Welcome back, ${r.user.full_name || r.user.email}`)
      // AuthGate validates the session and switches to the main app (no manual nav).
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Sign in failed')
    } finally { setBusy(false) }
  }

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to your diving company workspace.">
      <form onSubmit={submit} className="space-y-4">
        <label className="block">
          <span className="label flex items-center gap-1.5"><Mail size={12} /> Work Email</span>
          <input className="input" type="email" autoComplete="username" required
                 value={form.email} onChange={onSet('email')}
                 placeholder="you@yourcompany.com" />
        </label>

        <label className="block">
          <span className="label flex items-center gap-1.5"><Lock size={12} /> Password</span>
          <input className="input" type="password" autoComplete="current-password" required
                 value={form.password} onChange={onSet('password')}
                 placeholder="••••••••••" />
        </label>

        <button type="submit" disabled={busy} className="btn-primary w-full mt-2">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
          Sign In
        </button>
      </form>

      <div className="mt-6 pt-6 border-t border-white/5 text-center text-sm text-slate-400">
        New to NautiCAI?{' '}
        <Link to="/register" className="text-brand-300 hover:text-brand-200 font-semibold">
          Create a company account
        </Link>
      </div>
    </AuthLayout>
  )
}
