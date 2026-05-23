import { useState, useEffect, useRef, useMemo } from 'react'
import { ScanText, Image as ImageIcon, Loader2, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import VesselOcrCard from './VesselOcrCard'
import { useReport } from '../store/reportStore'
import { fetchImageObjectUrl } from '../lib/api'
import { applyVesselOcrToReport, findLocalImageUrl, ocrCandidateScore } from '../lib/vesselCover'

/**
 * Photographic Report opener: vessel name + cover photo.
 * Re-detect via OCR upload, cycle nameplate angles, or pick from hull grids.
 */
export default function PhotographicCoverPanel({ defaultOcrOpen = false, compact = false }) {
  const r = useReport()
  const {
    vessel, vesselImageId, vesselOcrConfidence,
    ensureVesselCover, syncVesselOcrFromServer, autoDetectVesselFromUpload,
    refreshCoverAlternates, cycleToNextCoverAlternate, applyCoverAlternate,
    images, coverAlternates,
  } = r

  const [ocrOpen, setOcrOpen] = useState(defaultOcrOpen)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [previewFailed, setPreviewFailed] = useState(false)
  const [cycling, setCycling] = useState(false)
  const syncRef = useRef(0)

  const hasName = Boolean((vessel.vesselName || '').trim())

  const coverIndex = useMemo(() => {
    const cur = vesselImageId?.trim()
    if (!cur || !coverAlternates?.length) return 0
    const idx = coverAlternates.findIndex((a) => a.imageId === cur)
    return idx >= 0 ? idx + 1 : 1
  }, [vesselImageId, coverAlternates])

  const coverTotal = coverAlternates?.length || 0

  useEffect(() => {
    const token = ++syncRef.current
    ;(async () => {
      const ids = r.collectUploadImageIds?.() || []
      if (ids.length >= 1) {
        const ok = await autoDetectVesselFromUpload()
        if (token !== syncRef.current) return
        await refreshCoverAlternates({ refreshOcr: false })
        if (ok) return
      }
      const id = vesselImageId?.trim()
      if (id) {
        await syncVesselOcrFromServer(id, { refresh: true })
      } else {
        ensureVesselCover(true)
      }
    })()
    return () => { syncRef.current += 1 }
  }, [vesselImageId, ensureVesselCover, syncVesselOcrFromServer, autoDetectVesselFromUpload])

  useEffect(() => {
    let revoke = null
    let cancelled = false
    const id = vesselImageId?.trim()
    if (!id) {
      setPreviewUrl(null)
      setLoadingPreview(false)
      setPreviewFailed(false)
      return undefined
    }

    const local = findLocalImageUrl(images, id)
    if (local) {
      setPreviewUrl(local)
      setPreviewFailed(false)
    }
    setLoadingPreview(!local)
    setPreviewFailed(false)

    fetchImageObjectUrl(id)
      .then((url) => {
        if (cancelled) return
        if (url) {
          revoke = url
          setPreviewUrl(url)
          setPreviewFailed(false)
        } else if (!local) {
          setPreviewFailed(true)
        }
      })
      .catch(() => {
        if (!cancelled && !local) setPreviewFailed(true)
      })
      .finally(() => {
        if (!cancelled) setLoadingPreview(false)
      })

    return () => {
      cancelled = true
      if (revoke && revoke !== local) {
        try { URL.revokeObjectURL(revoke) } catch { /* noop */ }
      }
    }
  }, [vesselImageId, images])

  const onOcrApply = (name, imageId, confidence = 1) => {
    const conf = Number(confidence) || 1
    const pick = {
      guess: name,
      imageId: imageId || '',
      confidence: conf,
      score: ocrCandidateScore(name, conf),
    }
    r.pushOcrCandidate({ vessel_ocr: pick, image_id: pick.imageId, best_guess: name })
    applyVesselOcrToReport(r, pick, { toast, force: true })
    setOcrOpen(false)
  }

  const onTryNextNameplate = async () => {
    setCycling(true)
    try {
      await cycleToNextCoverAlternate({ toast })
    } finally {
      setCycling(false)
    }
  }

  const onSelectAngle = async (alt) => {
    if (!alt?.imageId) return
    setCycling(true)
    try {
      await applyCoverAlternate(alt.imageId, { toast })
    } finally {
      setCycling(false)
    }
  }

  const onRefreshNameplates = async () => {
    setCycling(true)
    try {
      const alts = await refreshCoverAlternates({ refreshOcr: true })
      if (alts.length) {
        toast.success(`Found ${alts.length} nameplate photo${alts.length === 1 ? '' : 's'} in upload`)
      } else {
        toast('No extra nameplate photos detected in this batch.', { icon: 'ℹ️' })
      }
    } catch {
      toast.error('Could not refresh nameplate list')
    } finally {
      setCycling(false)
    }
  }

  return (
    <section className={compact ? 'rounded-xl ring-1 ring-white/10 bg-white/[0.02] p-4' : 'glass rounded-2xl p-5'}>
      <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-display font-semibold text-white flex items-center gap-2">
            <ImageIcon size={16} className="text-brand-300" />
            Photographic Report cover
          </h3>
          <p className="text-[11px] text-slate-400 mt-1 max-w-xl">
            Raw data may include several ship angles — each can read different text. Pick the
            cover page whose OCR matches the real vessel name, or use <strong className="text-slate-300">Next cover angle</strong> to try another photo.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 shrink-0">
          <button
            type="button"
            onClick={onTryNextNameplate}
            disabled={cycling}
            className="btn-primary text-xs"
            title="Re-OCR another nameplate photo and use the best vessel name read on that angle"
          >
            {cycling ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Next cover angle
            {coverTotal > 1 ? ` (${coverIndex}/${coverTotal})` : ''}
          </button>
          <button
            type="button"
            onClick={onRefreshNameplates}
            disabled={cycling}
            className="btn-outline text-xs"
            title="Re-scan all nameplate photos in the batch"
          >
            Refresh list
          </button>
          <button
            type="button"
            onClick={() => setOcrOpen((v) => !v)}
            className="btn-outline text-xs"
          >
            <ScanText size={12} />
            {ocrOpen ? 'Hide re-detect' : 'Re-detect from photo'}
          </button>
        </div>
      </header>

      <div className="flex flex-wrap gap-4 items-start">
        <div className="w-full sm:w-40 shrink-0">
          <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">Current cover</div>
          <div className="aspect-[4/3] rounded-xl ring-1 ring-white/10 bg-ink-900 overflow-hidden grid place-items-center">
            {loadingPreview && !previewUrl && <Loader2 size={20} className="animate-spin text-brand-300" />}
            {!loadingPreview && previewUrl && (
              <img src={previewUrl} alt="Report cover" className="h-full w-full object-cover" />
            )}
            {!loadingPreview && !previewUrl && (
              <span className="text-[10px] text-slate-500 px-2 text-center">
                {previewFailed ? 'Cover file not found on server' : 'No cover photo yet'}
              </span>
            )}
          </div>
        </div>
        <div className="flex-1 min-w-[200px] space-y-2 text-sm">
          <div>
            <span className="text-[10px] uppercase tracking-wider text-slate-400">Vessel name</span>
            <div className="font-semibold text-white mt-0.5">
              {hasName ? vessel.vesselName : '— not set —'}
            </div>
            {hasName && vesselOcrConfidence > 0 && (
              <div className="text-[10px] text-slate-400 mt-0.5">
                OCR confidence {(vesselOcrConfidence * 100).toFixed(0)}%
              </div>
            )}
          </div>
          {coverTotal > 1 && (
            <p className="text-[10px] text-slate-400">
              {coverTotal} nameplate photos in batch — use Try next if this angle mis-read the name.
            </p>
          )}
          {hasName && vesselImageId && (
            <span className="pill-success text-[10px]">Name and cover photo linked</span>
          )}
          {hasName && !vesselImageId && (
            <span className="pill-warn text-[10px]">
              Name set — pick a cover via re-detect or a hull photo
            </span>
          )}
        </div>
      </div>

      {coverTotal > 0 && (
        <div className="mt-4 border-t border-white/10 pt-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-2">
            Ship angles in upload — OCR text per photo
          </div>
          <ul className="space-y-1.5 max-h-40 overflow-y-auto">
            {coverAlternates.map((alt, i) => {
              const active = alt.imageId === vesselImageId
              return (
                <li key={alt.imageId}>
                  <button
                    type="button"
                    disabled={cycling}
                    onClick={() => onSelectAngle(alt)}
                    className={`w-full text-left rounded-lg px-3 py-2 text-xs transition ${
                      active
                        ? 'bg-brand-500/20 ring-1 ring-brand-400/50 text-white'
                        : 'bg-white/[0.04] hover:bg-white/[0.08] text-slate-300'
                    }`}
                  >
                    <span className="font-semibold text-slate-200">Angle {i + 1}</span>
                    <span className="mx-2 text-slate-500">·</span>
                    <span className="font-mono">{alt.guess}</span>
                    <span className="ml-2 text-slate-500">
                      ({(alt.confidence * 100).toFixed(0)}% OCR)
                    </span>
                    {alt.likelyTruncated && (
                      <span className="ml-2 text-amber-400/90">short read?</span>
                    )}
                    {active && <span className="ml-2 text-brand-300">← current cover</span>}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {ocrOpen && (
        <div className="mt-4 border-t border-white/10 pt-4">
          <VesselOcrCard defaultOpen onApply={onOcrApply} />
        </div>
      )}
    </section>
  )
}
