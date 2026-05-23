import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { checkBackendOnline } from '../lib/api'

/**
 * Shows a clear warning when the FastAPI backend is not reachable via the Vite /api proxy.
 * Generic browser "Not Found" toasts usually mean this banner should be visible.
 */
export default function BackendBanner() {
  const [online, setOnline] = useState(true)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    let timer
    let cancelled = false
    const tick = async () => {
      let ok = false
      for (let attempt = 0; attempt < 3 && !ok && !cancelled; attempt++) {
        ok = await checkBackendOnline()
        if (!ok && attempt < 2) {
          await new Promise((r) => setTimeout(r, 1500))
        }
      }
      if (cancelled) return
      setOnline(ok)
      setChecked(true)
      timer = setTimeout(tick, ok ? 20000 : 8000)
    }
    tick()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])

  if (!checked || online) return null

  return (
    <div
      role="alert"
      className="flex items-start gap-3 border-b border-amber-500/40 bg-amber-500/15 px-4 py-3 text-sm text-amber-100"
    >
      <AlertTriangle size={18} className="shrink-0 text-amber-300 mt-0.5" />
      <div>
        <div className="font-semibold text-amber-50">Backend not running</div>
        <p className="mt-1 text-amber-100/90">
          The app cannot reach the API at <code className="text-amber-200">http://127.0.0.1:8000</code>.
          Upload, OCR, and PDF will fail with &quot;Not Found&quot; until you start the server.
        </p>
        <pre className="mt-2 rounded-lg bg-ink-950/50 px-3 py-2 text-[11px] text-amber-100/80 overflow-x-auto">
{`cd F:\\Diving_company_project
.venv\\Scripts\\Activate.ps1
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000`}
        </pre>
        <p className="mt-2 text-[11px] text-amber-200/80">
          Keep this terminal open. Frontend must use the dev server (e.g. port 5173) so /api proxies to :8000.
        </p>
      </div>
    </div>
  )
}
