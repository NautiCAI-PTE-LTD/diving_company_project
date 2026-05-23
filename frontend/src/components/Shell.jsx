import { Routes, Route } from 'react-router-dom'
import Sidebar from './Sidebar'
import Topbar from './Topbar'
import BackendBanner from './BackendBanner'
import Dashboard from '../pages/Dashboard'
import NewReport from '../pages/NewReport'
import UploadImages from '../pages/UploadImages'
import Analysis from '../pages/Analysis'
import Reports from '../pages/Reports'
import Clients from '../pages/Clients'
import Settings from '../pages/Settings'

/** Main application chrome — only reachable after AuthGate confirms a valid session. */
export default function Shell() {
  return (
    <div className="app-bg flex min-h-screen text-slate-100">
      <Sidebar />
      <div className="flex min-h-screen flex-1 flex-col">
        <Topbar />
        <BackendBanner />
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
