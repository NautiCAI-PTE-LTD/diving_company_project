// Real API client. Talks to FastAPI backend at /api/* (proxied by Vite to :8000).
import axios from 'axios'
import { useAuth } from '../store/authStore'

export const api = axios.create({
  baseURL: '/api',
  timeout: 120_000,
})

// Attach Bearer token to every outgoing request.
api.interceptors.request.use((cfg) => {
  const token = useAuth.getState().token
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// Auto-logout on 401.
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      try { useAuth.getState().logout() } catch { /* noop */ }
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
  const { data } = await api.post('/analyze', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
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
  const { data } = await api.post('/analyze/video', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
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
  const { data } = await api.post('/ocr/vessel', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    params: persist ? { persist: true } : undefined,
  })
  return data    // { candidates: [{text,confidence,box}], best_guess, best_confidence, image_id?, url? }
}

// ---------------------------------------------------------------- reports ----
export async function createReport({ vessel, image_ids = [] }) {
  const { data } = await api.post('/reports', { vessel, image_ids })
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
    timeout: 600_000,   // PDF rendering with many images can take a while
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
    responseType: 'blob', timeout: 120_000,
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
  const { data } = await api.get(`/reports/${id}/pdf`, {
    responseType: 'blob', timeout: 120_000,
  })
  const url = URL.createObjectURL(data)
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
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
  const { data } = await api.post('/settings/logo', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
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
  try {
    const { data } = await api.get(`/images/${imageId}/file`, { responseType: 'blob' })
    return URL.createObjectURL(data)
  } catch {
    return ''
  }
}
