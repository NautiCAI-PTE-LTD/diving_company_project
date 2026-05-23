import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from '../store/authStore'
import { useBrand } from '../store/brandStore'
import { fetchMe } from '../lib/api'
import Login from '../pages/Login'
import Register from '../pages/Register'
import Shell from './Shell'

const FORCE_LOGIN_ON_START = import.meta.env.VITE_FORCE_LOGIN_ON_START === '1'

function PublicRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}

/**
 * No blank "securing session" screen.
 * Login shows whenever there is no token; saved sessions open the app after storage loads.
 */
export default function AuthGate() {
  const token = useAuth((s) => s.token)
  const setSession = useAuth((s) => s.setSession)
  const logout = useAuth((s) => s.logout)
  const refreshBrand = useBrand((s) => s.refresh)
  const [storageReady, setStorageReady] = useState(false)

  useEffect(() => {
    const finish = () => {
      if (FORCE_LOGIN_ON_START) logout()
      setStorageReady(true)
    }
    if (useAuth.persist.hasHydrated()) {
      finish()
      return
    }
    const unsub = useAuth.persist.onFinishHydration(finish)
    const fallback = setTimeout(finish, 400)
    return () => {
      unsub?.()
      clearTimeout(fallback)
    }
  }, [logout])

  useEffect(() => {
    if (!storageReady || !token) return

    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchMe()
        if (cancelled) return
        setSession({ token: r.access_token, user: r.user, company: r.company })
        refreshBrand().catch(() => {})
      } catch {
        if (!cancelled) logout()
      }
    })()

    return () => {
      cancelled = true
    }
  }, [storageReady, token, setSession, logout, refreshBrand])

  // Jetson: wait until we have cleared any saved token (still show login, not a blank page).
  if (FORCE_LOGIN_ON_START && !storageReady) {
    return <PublicRoutes />
  }

  if (!token) {
    return <PublicRoutes />
  }

  if (!storageReady) {
    return (
      <div className="app-bg grid min-h-screen place-items-center text-slate-400 text-sm">
        Loading workspace…
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/register" element={<Navigate to="/" replace />} />
      <Route path="/*" element={<Shell />} />
    </Routes>
  )
}
