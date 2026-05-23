import { useState } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  ScanText, Camera, Loader2, CheckCircle2, X, Sparkles, ChevronRight,
} from 'lucide-react'
import { ocrVessel } from '../lib/api'
import clsx from 'clsx'
import toast from 'react-hot-toast'

/**
 * Drop a photo where the vessel name is visible.
 *  • Hits POST /api/ocr/vessel?persist=true so the image is also saved to disk
 *    and tied to the report as the cover photograph.
 *  • Calls onApply(name, image_id) so the parent form can auto-fill both
 *    the vessel name AND remember the image id for the final report payload.
 */
export default function VesselOcrCard({ onApply, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const reset = () => {
    if (preview?.url) URL.revokeObjectURL(preview.url)
    setPreview(null); setResult(null)
  }

  const onDrop = async (files) => {
    const f = files[0]
    if (!f) return
    reset()
    const url = URL.createObjectURL(f)
    setPreview({ file: f, url })
    setBusy(true)
    try {
      const r = await ocrVessel(f, { persist: true })
      setResult(r)
      if (r.best_guess) toast.success(`Detected vessel: ${r.best_guess}`)
      else toast('No vessel name found — try another angle', { icon: '⚠️' })
    } catch (e) {
      toast.error(`Could not read text: ${e?.response?.data?.detail || e?.message || e}`)
    } finally { setBusy(false) }
  }

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop, accept: { 'image/*': [] }, multiple: false, maxSize: 20 * 1024 * 1024,
  })

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="glass lift w-full rounded-2xl p-4 text-left flex items-center gap-3">
        <div className="rounded-xl bg-gradient-to-br from-brand-400/25 to-accent-500/10 p-2.5 ring-1 ring-brand-400/30">
          <ScanText size={18} className="text-brand-300" />
        </div>
        <div className="flex-1">
          <div className="font-display text-sm font-semibold text-white">Auto-detect vessel name from photo</div>
          <div className="text-[11px] text-slate-400">Drop a bow/stern photo — we'll auto-fill the vessel name and add the photo to your report.</div>
        </div>
        <ChevronRight size={16} className="text-slate-400" />
      </button>
    )
  }

  return (
    <section className="glass rounded-2xl p-5">
      <header className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-brand-300" />
          <h3 className="font-display font-semibold text-white">Vessel-Name Auto-Detect</h3>
        </div>
        <button onClick={() => { setOpen(false); reset() }}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-white/5">
          <X size={14} />
        </button>
      </header>

      <div className="grid sm:grid-cols-2 gap-4">
        {/* Dropzone / preview */}
        <div
          {...getRootProps()}
          className={clsx(
            'cursor-pointer overflow-hidden rounded-xl border-2 border-dashed transition',
            isDragActive ? 'border-brand-400 bg-brand-400/10' : 'border-white/15 bg-white/[0.02] hover:border-brand-400/60',
            'min-h-[180px] grid place-items-center text-center p-4',
          )}
        >
          <input {...getInputProps()} />
          {preview ? (
            <div className="relative w-full">
              <img src={preview.url} alt="vessel"
                   className="mx-auto max-h-44 rounded-lg ring-1 ring-white/10 object-contain" />
              {busy && (
                <div className="absolute inset-0 grid place-items-center bg-ink-950/60 rounded-lg">
                  <Loader2 className="animate-spin text-brand-300" />
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <Camera size={22} className="text-brand-300" />
              <div className="text-sm font-semibold text-white">Drop bow / stern photo</div>
              <div className="text-[11px] text-slate-400">We'll read the painted name automatically.</div>
            </div>
          )}
        </div>

        {/* Candidates */}
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-2">Detected text</div>
          {!result && !busy && (
            <div className="text-xs text-slate-500">Awaiting an image…</div>
          )}
          {busy && (
            <div className="flex items-center gap-2 text-sm text-slate-300">
              <Loader2 className="animate-spin" size={14} /> Running OCR…
            </div>
          )}
          {result && (
            <>
              {result.best_guess ? (
                <div className="rounded-xl border border-brand-400/40 bg-brand-400/10 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-brand-200">Best Guess</div>
                  <div className="mt-1 font-mono text-lg font-bold text-white">{result.best_guess}</div>
                  <div className="mt-0.5 text-[11px] text-slate-300">
                    confidence {(result.best_confidence * 100).toFixed(1)}%
                  </div>
                  <button
                    type="button"
                    onClick={() => onApply?.(result.best_guess, result.image_id, result.best_confidence)}
                    className="btn-primary mt-3 w-full"
                  >
                    <CheckCircle2 size={14} /> Use for report — name &amp; Photographic cover
                  </button>
                </div>
              ) : (
                <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs text-slate-400">
                  No alphabetical candidate met the confidence threshold.
                </div>
              )}

              {result.candidates?.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  <div className="text-[10px] uppercase tracking-wider text-slate-400">Other candidates</div>
                  {result.candidates.map((c, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => onApply?.(c.text, result.image_id, c.confidence)}
                      className="flex w-full items-center justify-between rounded-lg bg-white/[0.04] px-3 py-1.5 text-left transition hover:bg-white/[0.08]"
                    >
                      <span className="font-mono text-sm text-white">{c.text}</span>
                      <span className="text-[11px] text-slate-400">{(c.confidence * 100).toFixed(0)}%</span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  )
}
