import { useEffect, useState } from 'react'
import { AlertTriangle, ShieldAlert } from 'lucide-react'
import {
  checkBackendOnline,
  getBuildApiRoot,
  getConfiguredApiRoot,
  isMixedContentBlocked,
  isProductionDeploy,
  resolveApiBaseURL,
} from '../lib/api'

/**
 * Warns when production UI cannot reach the API (mixed content, firewall, VM down).
 * Local dev uses Vite /api proxy — banner stays hidden when health succeeds.
 */
export default function BackendBanner() {
  const [online, setOnline] = useState(true)
  const [checked, setChecked] = useState(false)
  const mixed = isMixedContentBlocked()
  const apiRoot = getConfiguredApiRoot() || resolveApiBaseURL().replace(/\/api$/, '') || 'http://127.0.0.1:8000'
  const buildRoot = getBuildApiRoot()

  useEffect(() => {
    if (mixed) {
      setOnline(false)
      setChecked(true)
      return undefined
    }

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
  }, [mixed, apiRoot])

  if (!checked) return null
  if (!mixed && online) return null

  if (mixed) {
    return (
      <div
        role="alert"
        className="flex items-start gap-3 border-b border-rose-500/40 bg-rose-500/15 px-4 py-3 text-sm text-rose-100"
      >
        <ShieldAlert size={18} className="shrink-0 text-rose-300 mt-0.5" />
        <div>
          <div className="font-semibold text-rose-50">Uploads blocked (HTTPS → HTTP)</div>
          <p className="mt-1 text-rose-100/90">
            This page is <strong>HTTPS</strong> but the API is <code className="text-rose-200">{apiRoot}</code>.
            Browsers block image uploads in that setup — local <code className="text-rose-200">npm run dev</code> works
            because it proxies to <code className="text-rose-200">/api</code>.
          </p>
          <ul className="mt-2 list-disc pl-5 text-[12px] text-rose-100/85 space-y-1">
            <li>Use the <strong>HTTP</strong> S3 website URL (not CloudFront HTTPS), or</li>
            <li>Put HTTPS in front of the GCP API, or</li>
            <li>Settings → API connection → set an <code className="text-rose-200">https://</code> API URL</li>
          </ul>
        </div>
      </div>
    )
  }

  return (
    <div
      role="alert"
      className="flex items-start gap-3 border-b border-amber-500/40 bg-amber-500/15 px-4 py-3 text-sm text-amber-100"
    >
      <AlertTriangle size={18} className="shrink-0 text-amber-300 mt-0.5" />
      <div>
        <div className="font-semibold text-amber-50">Cannot reach API</div>
        <p className="mt-1 text-amber-100/90">
          Upload and Run AI will fail until the backend answers at{' '}
          <code className="text-amber-200">{apiRoot}</code>.
          {buildRoot && buildRoot !== apiRoot && (
            <> (build had <code className="text-amber-200">{buildRoot}</code> — override active)</>
          )}
        </p>
        {isProductionDeploy() ? (
          <p className="mt-2 text-[11px] text-amber-200/80">
            Check: GCP VM running · firewall TCP 8000 · log in on this exact site URL ·
            Settings → API connection if the VM IP changed.
          </p>
        ) : (
          <pre className="mt-2 rounded-lg bg-ink-950/50 px-3 py-2 text-[11px] text-amber-100/80 overflow-x-auto">
{`cd F:\\Diving_company_project
.venv\\Scripts\\Activate.ps1
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000`}
          </pre>
        )}
      </div>
    </div>
  )
}
