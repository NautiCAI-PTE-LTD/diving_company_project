import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import Dashboard from './pages/Dashboard'
import NewReport from './pages/NewReport'
import UploadImages from './pages/UploadImages'
import Analysis from './pages/Analysis'
import Reports from './pages/Reports'
import Clients from './pages/Clients'
import Settings from './pages/Settings'
import Login from './pages/Login'
import Register from './pages/Register'
import { useBrand } from './store/brandStore'
import { useAuth } from './store/authStore'
import { fetchMe } from './lib/api'
import { Loader2 } from 'lucide-react'

export default function App() {
  const token = useAuth((s) => s.token)
  const setSession = useAuth((s) => s.setSession)
  const refreshBrand = useBrand((s) => s.refresh)
  const [booting, setBooting] = useState(true)

  // App-boot: if there's a stored token, re-validate it with /auth/me so we know
  // the user/company are still valid (and to refresh the JWT). On success, pull
  // the branding so the sidebar shows the correct logo immediately.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (token) {
        try {
          const r = await fetchMe()
          if (cancelled) return
          setSession({ token: r.access_token, user: r.user, company: r.company })
          await refreshBrand()
        } catch { /* interceptor handles 401 */ }
      }
      if (!cancelled) setBooting(false)
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (booting) {
    return (
      <div className="min-h-screen grid place-items-center bg-ink-950 text-slate-300">
        <div className="flex items-center gap-3">
          <Loader2 className="animate-spin text-brand-300" />
          <span className="text-sm">Loading workspace…</span>
        </div>
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/login"    element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
      <Route path="/*"        element={<Protected><Shell /></Protected>} />
    </Routes>
  )
}

function Protected({ children }) {
  const token = useAuth((s) => s.token)
  const loc = useLocation()
  if (!token) return <Navigate to="/login" replace state={{ from: loc }} />
  return children
}

function PublicOnly({ children }) {
  const token = useAuth((s) => s.token)
  if (token) return <Navigate to="/" replace />
  return children
}

function Shell() {
  return (
    <div className="app-bg flex min-h-screen text-slate-100">
      <Sidebar />
      <div className="flex min-h-screen flex-1 flex-col">
        <Topbar />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Routes>
            <Route path="/"          element={<Dashboard />} />
            <Route path="new"        element={<NewReport />} />
            <Route path="upload"     element={<UploadImages />} />
            <Route path="analysis"   element={<Analysis />} />
            <Route path="reports"    element={<Reports />} />
            <Route path="clients"    element={<Clients />} />
            <Route path="settings"   element={<Settings />} />
            <Route path="*"          element={<NotFound />} />
          </Routes>
        </main>
        <footer className="border-t border-white/5 px-6 py-4 text-center text-[11px] text-slate-500">
          © {new Date().getFullYear()} NautiCAI · Built for diving companies
        </footer>
      </div>
    </div>
  )
}

function NotFound() {
  return (
    <div className="grid place-items-center py-24">
      <div className="text-center">
        <div className="font-mono text-7xl text-brand-300">404</div>
        <div className="mt-2 text-slate-400">That route is not in our charts.</div>
      </div>
    </div>
  )
}
