import { useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Sparkles, Loader2, Trash2, ScanSearch, ImagePlus, Video,
  Film, Clock, Check, X, AlertTriangle, FolderPlus,
} from 'lucide-react'
import toast from 'react-hot-toast'
import ImageDropzone from '../components/ImageDropzone'
import { HULL_REGIONS } from '../lib/constants'
import {
  analyzeImage, analyzeVideo, isVideoFile, fetchImageObjectUrl,
  isMixedContentBlocked, uploadErrorMessage,
} from '../lib/api'
import { useAuth } from '../store/authStore'
import { isCoverOnlyResult, ocrCandidateScore, pickBestVesselOcr } from '../lib/vesselCover'
import { uid } from '../lib/uid'

/**
 * Image / Video / Folder studio.
 *
 * Each row in `items` is either:
 *   • kind:'image'  →  one upload, becomes one analysis result
 *   • kind:'video'  →  one upload, expands to N frame results (each rendered
 *                       like an image card in the auto-routed regions below)
 */
export default function UploadImages() {
  const [items, setItems] = useState([])
  const itemsRef = useRef(items)
  itemsRef.current = items
  const token = useAuth((s) => s.token)
  const [busy, setBusy] = useState(false)
  const [vesselCover, setVesselCover] = useState(null) // { name, imageId, url, fileName }

  // -------- adding files (handles drop + folder pick + paste) --------
  const addFiles = (files) => {
    const next = files.map((file) => ({
      id: uid(),
      file,
      url: URL.createObjectURL(file),
      name: file.name,
      size: file.size,
      kind: isVideoFile(file) ? 'video' : 'image',
      status: 'pending',
      progress: 0,
      result: null,    // {region, stage, …} for image; {frames:[…]} for video
      region: null,    // primary region (videos: dominant region across frames)
      error: null,
    }))
    setItems((prev) => [...next, ...prev])
  }

  const remove = (id) => setItems((prev) => prev.filter((i) => i.id !== id))

  // -------- analysis dispatch ------------------------------------------
  const analyzeOne = async (id) => {
    const it = itemsRef.current.find((i) => i.id === id)
    if (!it || it.status === 'analyzing') return
    if (!it.file) {
      toast.error(`${it.name}: file missing — re-add from folder or Browse Files`)
      return
    }

    setItems((p) => p.map((i) => i.id === id ? { ...i, status: 'analyzing', progress: 0, error: null } : i))

    try {
      if (it.kind === 'video') {
        const data = await analyzeVideo(it.file, {
          strideSec: 2.0, maxFrames: 24,
          onProgress: (frac) =>
            setItems((p) => p.map((i) => i.id === id ? { ...i, progress: frac } : i)),
        })
        // Fetch each extracted frame as an authenticated blob URL so <img> can render it.
        const thumbs = await Promise.all(
          data.frames.map((f) => fetchImageObjectUrl(f.image_id)),
        )
        data.frames = data.frames.map((f, idx) => ({ ...f, thumb_url: thumbs[idx] }))
        const counts = {}
        for (const f of data.frames) {
          if (!isCoverOnlyResult(f)) counts[f.region.id] = (counts[f.region.id] || 0) + 1
        }
        for (const f of data.frames) {
          if (!isCoverOnlyResult(f) || !f.vessel_ocr?.best_guess) continue
          const prev = vesselCover
            ? {
              confidence: vesselCover.confidence || 0,
              guess: vesselCover.name || '',
              imageId: vesselCover.imageId || '',
              score: vesselCover.score || ocrCandidateScore(vesselCover.name, vesselCover.confidence),
            }
            : {}
          const best = pickBestVesselOcr([f], prev)
          if (best.guess) {
            setVesselCover((vc) => (!vc || best.score > (vc.score || 0))
              ? {
                name: best.guess,
                imageId: best.imageId,
                fileName: it.name,
                url: it.url,
                confidence: best.confidence,
                score: best.score,
              }
              : vc)
          }
        }
        const region = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || null
        setItems((p) => p.map((i) =>
          i.id === id ? { ...i, status: 'done', result: data, region, progress: 1 } : i,
        ))
      } else {
        const result = await analyzeImage(it.file)
        if (isCoverOnlyResult(result)) {
          const vo = result.vessel_ocr
          const prev = vesselCover
            ? {
              confidence: vesselCover.confidence || 0,
              guess: vesselCover.name || '',
              imageId: vesselCover.imageId || '',
              score: vesselCover.score || ocrCandidateScore(vesselCover.name, vesselCover.confidence),
            }
            : {}
          const best = pickBestVesselOcr([result], prev)
          if (best.guess && (!vesselCover || best.score > (vesselCover.score || 0))) {
            setVesselCover({
              name: best.guess,
              imageId: best.imageId || result.image_id,
              url: it.url,
              fileName: it.name,
              confidence: best.confidence,
              score: best.score,
            })
          }
          setItems((p) => p.map((i) =>
            i.id === id ? { ...i, status: 'done', result, region: 'vessel_cover', progress: 1 } : i,
          ))
        } else {
          setItems((p) => p.map((i) =>
            i.id === id ? { ...i, status: 'done', result, region: result.region.id, progress: 1 } : i,
          ))
        }
      }
    } catch (err) {
      const msg = uploadErrorMessage(err)
      setItems((p) => p.map((i) =>
        i.id === id ? { ...i, status: 'error', error: msg } : i,
      ))
      toast.error(`${it.name}: ${msg}`, { duration: 8000 })
    }
  }

  const analyzeAll = async () => {
    if (isMixedContentBlocked()) {
      toast.error(uploadErrorMessage({}), { duration: 10000 })
      return
    }
    if (!token) {
      toast.error('Log in on this site URL first — uploads are sent to the cloud API with your account token')
      return
    }
    const pending = itemsRef.current.filter((i) => i.status === 'pending' || i.status === 'error')
    if (!pending.length) {
      toast('Nothing to analyse — add images or videos first')
      return
    }
    setBusy(true)
    try {
      // Process videos sequentially (heavy), images can run in parallel.
      const videos = pending.filter((i) => i.kind === 'video')
      const images = pending.filter((i) => i.kind === 'image')
      await Promise.all(images.map((i) => analyzeOne(i.id)))
      for (const v of videos) {
        await analyzeOne(v.id)
      }
      toast.success(`Analysed ${pending.length} item${pending.length === 1 ? '' : 's'}`)
    } finally { setBusy(false) }
  }

  // -------- derived view -----------------------------------------------
  const counts = useMemo(() => {
    const c = { total: items.length, images: 0, videos: 0, done: 0, frames: 0 }
    for (const it of items) {
      if (it.kind === 'image') c.images++
      else c.videos++
      if (it.status === 'done') c.done++
      if (it.kind === 'video' && it.result?.frames) c.frames += it.result.frames.length
    }
    return c
  }, [items])

  // Flatten everything into per-region cards for the grouped layout.
  const flatCards = useMemo(() => {
    const cards = []
    for (const it of items) {
      if (it.kind === 'image') {
        if (it.region === 'vessel_cover' || isCoverOnlyResult(it.result)) continue
        cards.push({
          kind: 'image',
          id: it.id, parentId: it.id,
          name: it.name, url: it.url, status: it.status,
          region: it.region, result: it.result,
        })
      } else if (it.result?.frames) {
        for (const f of it.result.frames) {
          if (isCoverOnlyResult(f)) continue
          cards.push({
            kind: 'frame',
            id: f.image_id, parentId: it.id,
            name: `${it.name} · t=${f.ts_sec.toFixed(1)}s`,
            url: f.thumb_url || '',
            status: 'done',
            region: f.region.id, result: f,
          })
        }
      }
    }
    return cards
  }, [items])

  const grouped = HULL_REGIONS.map((r) => ({
    region: r,
    cards: flatCards.filter((c) => c.region === r.id),
  })).filter((g) => g.cards.length)

  const unrouted = flatCards.filter((c) => !c.region)
  const pendingVideos = items.filter((i) => i.kind === 'video' && i.status !== 'done')
  const pendingImages = items.filter((i) => i.kind === 'image' && i.status === 'pending')

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-brand-300">Inspection Intake</div>
          <h1 className="mt-1 font-display text-2xl font-bold text-white">Auto-route photos, videos & folders</h1>
          <p className="text-sm text-slate-400">
            Drop an entire dive folder — NautiCAI sorts each photo or ROV frame into its hull region
            and tags it with the cleaning stage and dominant fouling species.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="pill-mute"><ImagePlus size={11} /> {counts.images} photo{counts.images === 1 ? '' : 's'}</span>
          <span className="pill-mute"><Video size={11} /> {counts.videos} video{counts.videos === 1 ? '' : 's'}</span>
          {counts.frames > 0 && <span className="pill-mute"><Film size={11} /> {counts.frames} frames</span>}
          <button className="btn-primary" onClick={analyzeAll}
            disabled={!items.length || busy ||
              (pendingImages.length === 0 && pendingVideos.length === 0)}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            Run AI on All
          </button>
        </div>
      </header>

      <ImageDropzone onFiles={addFiles} />

      {vesselCover?.name && (
        <section className="glass rounded-2xl p-4 flex flex-wrap items-center gap-3 border border-emerald-500/20">
          <ScanSearch size={18} className="text-emerald-400 shrink-0" />
          <div>
            <div className="text-xs text-slate-400">Vessel name (Photographic Report cover)</div>
            <div className="font-display font-semibold text-white">{vesselCover.name}</div>
            <div className="text-[11px] text-slate-500">{vesselCover.fileName}</div>
          </div>
          {vesselCover.url && (
            <img src={vesselCover.url} alt="" className="h-16 w-24 object-cover rounded-lg ml-auto" />
          )}
        </section>
      )}

      {/* video status panel */}
      <AnimatePresence>
        {items.filter((i) => i.kind === 'video').length > 0 && (
          <motion.section
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            className="glass rounded-2xl p-5">
            <header className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Video size={16} className="text-brand-300" />
                <h3 className="font-display text-base font-semibold text-white">ROV & Dive Videos</h3>
              </div>
              <span className="text-xs text-slate-400">{items.filter(i => i.kind === 'video').length} loaded</span>
            </header>
            <div className="grid md:grid-cols-2 gap-3">
              {items.filter(i => i.kind === 'video').map((v) => (
                <VideoCard key={v.id} item={v} onAnalyze={analyzeOne} onRemove={remove} />
              ))}
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      {unrouted.length > 0 && (
        <Section title="Pending" subtitle="Awaiting analysis">
          <Grid cards={unrouted} onRemove={remove} onAnalyze={(id) =>
            analyzeOne(items.find((i) => i.id === id)?.id || id)
          } items={items} />
        </Section>
      )}

      {grouped.map(({ region, cards }) => (
        <Section key={region.id} title={region.displayLabel}
                 subtitle={`${cards.length} item${cards.length === 1 ? '' : 's'}`}>
          <Grid cards={cards} onRemove={remove} onAnalyze={(id) =>
            analyzeOne(items.find((i) => i.id === id)?.id || id)
          } items={items} />
        </Section>
      ))}
    </div>
  )
}

// ============================================================================
function VideoCard({ item, onAnalyze, onRemove }) {
  const pct = Math.round((item.progress || 0) * 100)
  const v = item
  const frameCount = v.result?.frames?.length || 0
  const vesselGuess = v.result?.vessel_ocr?.best_guess || ''
  const dur = v.result?.video?.duration_sec
  return (
    <div className="rounded-xl ring-1 ring-white/10 bg-white/[0.03] overflow-hidden">
      <div className="relative aspect-video bg-black">
        <video src={v.url} controls muted className="h-full w-full object-contain" />
        {v.status === 'analyzing' && (
          <div className="absolute inset-0 bg-black/55 grid place-items-center text-center">
            <div className="space-y-1">
              <Loader2 size={20} className="animate-spin text-brand-300 mx-auto" />
              <div className="text-xs text-white">
                {pct < 100 ? `Uploading ${pct}%` : 'Extracting frames & running AI…'}
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="p-3 space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-white truncate">{v.name}</div>
            <div className="text-[11px] text-slate-400 flex items-center gap-2 mt-0.5">
              <Clock size={10} /> {dur ? `${dur.toFixed(1)}s` : `${(v.size / 1024 / 1024).toFixed(1)} MB`}
              {frameCount > 0 && <span>· {frameCount} frames analysed</span>}
            </div>
          </div>
          <button onClick={() => onRemove(v.id)} className="btn-ghost !px-1.5">
            <X size={12} />
          </button>
        </div>
        {v.status === 'done' && (
          <div className="flex flex-wrap gap-1 text-[11px]">
            <span className="pill-brand"><Check size={10} /> Done</span>
            {v.result?.video && (
              <span className="pill-mute">
                kept {v.result.video.frames_kept}/{v.result.video.total_frames_scanned}
                {v.result.video.frames_dropped_blurry > 0 &&
                  ` · ${v.result.video.frames_dropped_blurry} blurry`}
              </span>
            )}
            {vesselGuess && (
              <span className="pill-brand">OCR: {vesselGuess}</span>
            )}
          </div>
        )}
        {v.status === 'error' && (
          <div className="flex items-center gap-1 text-[11px] text-rose-300">
            <AlertTriangle size={11} /> {v.error}
          </div>
        )}
        {v.status === 'pending' && (
          <button onClick={() => onAnalyze(v.id)} className="btn-primary text-xs w-full">
            <ScanSearch size={12} /> Analyse Video
          </button>
        )}
      </div>
    </div>
  )
}

function Section({ title, subtitle, children }) {
  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="glass rounded-2xl p-5">
      <header className="flex items-end justify-between gap-3 mb-4">
        <div>
          <h3 className="font-display text-base font-semibold text-white">{title}</h3>
          <div className="text-xs text-slate-400">{subtitle}</div>
        </div>
      </header>
      {children}
    </motion.section>
  )
}

function Grid({ cards, onRemove, onAnalyze, items }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
      {cards.map((c) => (
        <div key={c.id} className="group relative overflow-hidden rounded-xl border border-white/10 bg-ink-900">
          <img src={c.url} alt={c.name} className="aspect-square w-full object-cover transition group-hover:scale-105" />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink-950 via-ink-950/40 to-transparent" />
          <div className="absolute right-2 top-2 flex gap-1 opacity-0 transition group-hover:opacity-100">
            {c.kind === 'image' && (
              <button onClick={() => onAnalyze(c.parentId)} className="rounded-lg bg-ink-900/80 p-1.5 text-brand-300 hover:bg-ink-800" title="Analyse">
                <ScanSearch size={14} />
              </button>
            )}
            <button onClick={() => onRemove(c.parentId)} className="rounded-lg bg-ink-900/80 p-1.5 text-rose-300 hover:bg-ink-800"
                    title={c.kind === 'frame' ? 'Remove parent video' : 'Remove'}>
              <Trash2 size={14} />
            </button>
          </div>
          {c.kind === 'frame' && (
            <div className="absolute left-2 top-2">
              <span className="pill-brand text-[10px]"><Film size={9} /> frame</span>
            </div>
          )}
          <div className="absolute inset-x-0 bottom-0 p-2.5 text-[11px]">
            <div className="truncate font-semibold text-white">{c.name}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {c.status === 'analyzing' && <span className="pill-brand"><Loader2 size={11} className="animate-spin" /> AI</span>}
              {c.result && (
                <>
                  <span className="pill-brand">{c.result.region?.id}</span>
                  <span className="pill-mute">{c.result.stage?.id}</span>
                  <span className="pill-warn">{Math.round(c.result.fouling_pct)}%</span>
                </>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
