// Real API client. Dev: /api (Vite proxy → :8000). Production (S3/CloudFront): set VITE_API_URL.
import axios from 'axios'
import { useAuth } from '../store/authStore'

const API_ROOT_STORAGE = 'nauticai_api_root'

/** Built-in production API (from `npm run build`) or empty in local dev. */
export function getBuildApiRoot() {
  return (import.meta.env.VITE_API_URL || '').trim().replace(/\/$/, '')
}

/** Runtime override (Settings) — survives S3 redeploys when the VM IP changes. */
export function getApiRootOverride() {
  try {
    return (localStorage.getItem(API_ROOT_STORAGE) || '').trim().replace(/\/$/, '')
  } catch {
    return ''
  }
}

export function setApiRootOverride(url) {
  const v = (url || '').trim().replace(/\/$/, '')
  try {
    if (!v) localStorage.removeItem(API_ROOT_STORAGE)
    else localStorage.setItem(API_ROOT_STORAGE, v)
  } catch { /* private browsing */ }
}

/** S3 deploy: `public/runtime-config.js` sets window.__NAUTICAI_API_URL__ before the app loads. */
export function getRuntimeApiRoot() {
  if (typeof window === 'undefined') return ''
  const v = window.__NAUTICAI_API_URL__
  return (v == null ? '' : String(v)).trim().replace(/\/$/, '')
}

/** Public API origin without `/api`, e.g. `http://34.87.86.250:8000` or `''` in dev. */
export function getConfiguredApiRoot() {
  return getApiRootOverride() || getRuntimeApiRoot() || getBuildApiRoot()
}

export function isProductionDeploy() {
  return Boolean(getConfiguredApiRoot())
}

/** @returns {string} e.g. '/api' or 'http://34.87.86.250:8000/api' */
export function resolveApiBaseURL() {
  const raw = getConfiguredApiRoot()
  if (!raw) return '/api'
  return raw.endsWith('/api') ? raw : `${raw}/api`
}

/** HTTPS UI cannot call an HTTP API — uploads fail with generic "Network Error". */
export function isMixedContentBlocked() {
  if (typeof window === 'undefined') return false
  if (window.location.protocol !== 'https:') return false
  const root = getConfiguredApiRoot().toLowerCase()
  return root.startsWith('http://')
}

export const api = axios.create({
  baseURL: resolveApiBaseURL(),
  timeout: 120_000,
})

/** Let the browser set multipart boundary — never force Content-Type on FormData. */
const formPost = (url, formData, config = {}) => {
  const headers = { ...(config.headers || {}) }
  delete headers['Content-Type']
  delete headers['content-type']
  return api.post(url, formData, { ...config, headers })
}

/** Sync message for upload/analyze failures (used in toasts). */
export function uploadErrorMessage(err) {
  if (isMixedContentBlocked() && !err?.response) {
    return (
      'Browser blocked the HTTP API from this HTTPS site. Open the UI via the S3 HTTP website URL, '
      + 'or set an HTTPS API URL under Settings → API connection.'
    )
  }
  const raw = err?.response?.data
  if (!raw) {
    const msg = err?.message || ''
    if (/network|failed to fetch|ECONNREFUSED|ERR_CONNECTION|ERR_BLOCKED/i.test(msg)) {
      const hint = getConfiguredApiRoot() || 'http://127.0.0.1:8000 (local dev uses /api proxy)'
      return `Cannot reach the API at ${hint} — VM running, port 8000 open, and logged in on this URL?`
    }
    return msg || String(err)
  }
  if (typeof raw === 'string') return raw
  if (raw?.detail) {
    const d = raw.detail
    return typeof d === 'string' ? d : JSON.stringify(d)
  }
  return err?.message || 'Upload failed'
}

/** Turn API errors into a short message (handles blob 404 bodies from PDF routes). */
export async function apiErrorMessage(err) {
  const raw = err?.response?.data
  if (!raw) {
    if (isMixedContentBlocked()) {
      return uploadErrorMessage(err)
    }
    if (/network|ECONNREFUSED|ERR_CONNECTION|failed to fetch/i.test(err?.message || '')) {
      const hint = getConfiguredApiRoot() || 'http://127.0.0.1:8000'
      return `Cannot reach the API at ${hint}`
    }
    return err?.message || String(err)
  }
  if (typeof raw === 'string') return raw
  if (raw?.detail) {
    const d = raw.detail
    return typeof d === 'string' ? d : JSON.stringify(d)
  }
  if (typeof Blob !== 'undefined' && raw instanceof Blob) {
    try {
      const text = await raw.text()
      const j = JSON.parse(text)
      return j.detail || text
    } catch {
      return err?.message || 'Request failed'
    }
  }
  return err?.message || String(err)
}

/** True when the FastAPI backend answers /api/health. */
export async function checkBackendOnline() {
  try {
    const { data } = await api.get('/health', { timeout: 5000 })
    return Boolean(data?.ok)
  } catch {
    return false
  }
}

/** User-friendly text when detail is the generic Starlette 404. */
export function friendlyApiDetail(detail, fallback = 'Request failed') {
  const d = (detail || '').trim()
  if (!d || d === 'Not Found') {
    const hint = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
    return `API not reachable — check backend at ${hint}`
  }
  if (d === 'image not found' || d === 'image file missing') {
    return 'Photo not on server — re-upload on Upload Raw Data and wait until analysis finishes'
  }
  return d
}

// Attach Bearer token; refresh baseURL when API override changes.
api.interceptors.request.use((cfg) => {
  cfg.baseURL = resolveApiBaseURL()
  const token = useAuth.getState().token
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// Auto-logout on 401 and return to the login screen.
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      const path = window.location.pathname
      const url = err?.config?.url || ''
      const onAuthScreen = path === '/login' || path === '/register'
      const duringBootCheck = url.includes('/auth/me')
      try { useAuth.getState().logout() } catch { /* noop */ }
      if (!onAuthScreen && !duringBootCheck) {
        window.location.replace('/login')
      }
    }
    return Promise.reject(err)
  },
)

// Resolve a backend image URL to an absolute path (used by <img src>)
export const fileUrl = (path) => path?.startsWith('http') ? path : path

// ---------------------------------------------------------------- auth ----
export async function register(payload) {
  const { data } = await api.post('/auth/register', payload)
  return data    // { access_token, user, company }
}

export async function login(payload) {
  const { data } = await api.post('/auth/login', payload)
  return data
}

export async function fetchMe() {
  const { data } = await api.get('/auth/me')
  return data
}

// ---------------------------------------------------------------- clients ----
// The "clients directory" — vessel owners the diving company services.
// Entered once, reused on every new inspection.
export async function listClients({ q } = {}) {
  const { data } = await api.get('/clients', { params: q ? { q } : {} })
  return data    // ClientRow[]
}

export async function createClient(payload) {
  const { data } = await api.post('/clients', payload)
  return data
}

export async function updateClient(id, payload) {
  const { data } = await api.put(`/clients/${id}`, payload)
  return data
}

export async function deleteClient(id) {
  await api.delete(`/clients/${id}`)
}

// ---------------------------------------------------------------- inference ----
export const VIDEO_EXTS = ['.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm']
export const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp']

export function isVideoFile(file) {
  if (!file) return false
  if (file.type?.startsWith('video/')) return true
  const n = (file.name || '').toLowerCase()
  return VIDEO_EXTS.some((ext) => n.endsWith(ext))
}

export function isImageFile(file) {
  if (!file) return false
  if (file.type?.startsWith('image/')) return true
  const n = (file.name || '').toLowerCase()
  return IMAGE_EXTS.some((ext) => n.endsWith(ext))
}

export async function analyzeImage(file, { regionHint } = {}) {
  const fd = new FormData()
  fd.append('image', file)
  if (regionHint) fd.append('region_hint', regionHint)
  const { data } = await formPost('/analyze', fd, {
    // 10 min ceiling per request. The UI caps concurrency at 4, so the
    // worst-case wait per request is (4 × per-image model time + a bit
    // of OCR on overview shots). On CPU-only deploys a single analyze
    // can take ~10 s; 10 min comfortably absorbs the backend queue for
    // large batches (1000+ photos) without spurious timeouts.
    timeout: 600_000,
  })
  return data    // { image_id, url, region:{id,display,confidence}, stage:{id,confidence}, species:{...}, fouling_pct, severity, width, height, filename, vessel_ocr? }
}

export async function analyzeVideo(file, { strideSec = 2.0, maxFrames = 24, onProgress } = {}) {
  const fd = new FormData()
  fd.append('video', file)
  fd.append('stride_sec', String(strideSec))
  fd.append('max_frames', String(maxFrames))
  const { data } = await formPost('/analyze/video', fd, {
    timeout: 600_000,  // up to 10 minutes for long ROV footage
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) onProgress(evt.loaded / evt.total)
    },
  })
  return data    // { source_filename, video:{...}, frame_count, frames:[…], vessel_ocr:{best_guess,confidence,image_id} }
}

export async function ocrVessel(file, { persist = false } = {}) {
  const fd = new FormData()
  fd.append('image', file)
  const { data } = await formPost('/ocr/vessel', fd, {
    params: persist ? { persist: true } : undefined,
  })
  return data    // { candidates: [{text,confidence,box}], best_guess, best_confidence, image_id?, url? }
}

// ---------------------------------------------------------------- reports ----
export async function createReport({
  vessel,
  image_ids = [],
  region_inspections = {},
  vessel_image_id = '',
  client_id = null,
} = {}) {
  const { data } = await api.post('/reports', {
    vessel,
    image_ids,
    region_inspections,
    vessel_image_id: vessel_image_id || '',
    client_id,
  })
  return data
}

export async function listReports({ status, q } = {}) {
  const { data } = await api.get('/reports', { params: { status, q } })
  return data
}

export async function getReport(id) {
  const { data } = await api.get(`/reports/${id}`)
  return data
}

export async function patchReport(id, payload) {
  const { data } = await api.patch(`/reports/${id}`, payload)
  return data
}

export async function deleteReport(id) {
  const { data } = await api.delete(`/reports/${id}`)
  return data
}

export async function generateReportPdf(id) {
  const { data } = await api.post(`/reports/${id}/generate`, null, {
    timeout: 900_000,   // PDF rendering with many images can take a while
  })
  return data
}

export function reportPdfDownloadUrl(id) {
  return `/api/reports/${id}/pdf`
}

/** Download the report PDF via authenticated fetch and trigger a browser save.
 *  Using <a href> or window.open won't include the Bearer token, so we have to
 *  pull the blob ourselves. */
export async function downloadReportPdf(id, vesselName = '') {
  const { data, headers } = await api.get(`/reports/${id}/pdf`, {
    responseType: 'blob', timeout: 900_000,
  })
  const safe = (vesselName || id).replace(/[^A-Za-z0-9_\-]+/g, '_').slice(0, 60)
  const filename =
    headers?.['content-disposition']?.match(/filename="?([^";]+)"?/i)?.[1] ||
    `${safe || id}.pdf`
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}

/** Open the PDF in a new tab. Same auth dance — fetch as blob then open the
 *  object URL so the browser opens it inline. */
export async function openReportPdf(id) {
  try {
    const { data, headers } = await api.get(`/reports/${id}/pdf`, {
      responseType: 'blob', timeout: 900_000,
    })
    const ct = (headers?.['content-type'] || '').toLowerCase()
    if (ct.includes('json') || (data?.type || '').includes('json')) {
      const text = await data.text()
      let detail = text
      try { detail = JSON.parse(text).detail || text } catch { /* keep text */ }
      throw new Error(friendlyApiDetail(detail, 'PDF not available'))
    }
    if (!data?.size) {
      throw new Error('PDF file is empty — try Generate PDF again from Reports.')
    }
    const url = URL.createObjectURL(data)
    window.open(url, '_blank', 'noopener,noreferrer')
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (err) {
    const msg = await apiErrorMessage(err)
    throw new Error(friendlyApiDetail(msg, msg))
  }
}

// ---------------------------------------------------------------- images ----
export async function listImages({ report_id } = {}) {
  const { data } = await api.get('/images', { params: { report_id } })
  return data
}

export async function deleteImage(id) {
  const { data } = await api.delete(`/images/${id}`)
  return data
}

// ---------------------------------------------------------------- stats / meta ----
export async function getStats() {
  const { data } = await api.get('/stats')
  return data
}

export async function getMeta() {
  const { data } = await api.get('/meta')
  return data
}

// ---------------------------------------------------------------- settings ----
export async function getSettings() {
  const { data } = await api.get('/settings')
  return data
}

export async function saveSettings(payload) {
  const { data } = await api.put('/settings', payload)
  return data
}

export async function uploadLogo(file) {
  const fd = new FormData()
  fd.append('image', file)
  const { data } = await formPost('/settings/logo', fd)
  return data
}

/** Small multipart POST to verify browser → API uploads (auth required). */
export async function testUploadEcho(file) {
  const fd = new FormData()
  fd.append('image', file)
  const { data } = await formPost('/diagnostics/upload-echo', fd, { timeout: 60_000 })
  return data
}

export async function deleteLogo() {
  const { data } = await api.delete('/settings/logo')
  return data
}

/** Fetch the current company's logo (auth-protected) and return an object URL.
 *  Returns null if no logo is set or the request fails. */
export async function fetchLogoObjectUrl() {
  try {
    const { data } = await api.get('/settings/logo', { responseType: 'blob' })
    return URL.createObjectURL(data)
  } catch {
    return null
  }
}

/** Fetch a protected image (e.g. an extracted video frame) and turn it into
 *  an `<img src>`-friendly blob URL.  Returns '' on failure. */
export async function fetchImageObjectUrl(imageId) {
  if (!imageId?.trim()) return ''
  try {
    const { data } = await api.get(`/images/${imageId}/file`, { responseType: 'blob' })
    if (!data?.size) return ''
    return URL.createObjectURL(data)
  } catch {
    return ''
  }
}

/** Automated vessel name + cover from analysed image ids (no manual vessel list). */
export async function autoDetectVessel(imageIds, { pinnedVesselName = '' } = {}) {
  const { data } = await api.post('/vessels/auto-detect', {
    image_ids: imageIds,
    pinned_vessel_name: pinnedVesselName || '',
  })
  return data
}

/** All nameplate photos in the batch with OCR names (for "Try next nameplate"). */
export async function fetchCoverAlternates(imageIds, { refreshOcr = false } = {}) {
  const { data } = await api.post('/vessels/cover-alternates', {
    image_ids: imageIds,
    pinned_vessel_name: '',
  }, {
    params: refreshOcr ? { refresh: true } : {},
    timeout: 600_000,
  })
  return data
}

/** Re-read vessel name OCR for an uploaded image (fixes stale VERSTONE-style guesses). */
export async function fetchImageVesselOcr(imageId, { refresh = true } = {}) {
  const { data } = await api.get(`/images/${imageId}/vessel-ocr`, {
    params: refresh ? { refresh: true } : {},
  })
  return data
}
