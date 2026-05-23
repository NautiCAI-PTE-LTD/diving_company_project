import { useState, useMemo, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, ArrowRight, Anchor, ShieldCheck, Sparkles, FileDown, Loader2,
  Clock, Camera, ListChecks, ClipboardCheck, Plus, X, ChevronDown, ChevronRight,
  Trash2, AlertTriangle, Video, Film, Check, Wand2, Building2, Users,
  Image as ImageIcon,
} from 'lucide-react'
import toast from 'react-hot-toast'
import Stepper from '../components/Stepper'
import ImageDropzone from '../components/ImageDropzone'
import PhotographicCoverPanel from '../components/PhotographicCoverPanel'
import ClientPicker from '../components/ClientPicker'
import { useReport, emptyFindings } from '../store/reportStore'
import { HULL_REGIONS, VESSEL_TYPES, VESSEL_CLASSES } from '../lib/constants'
import {
  analyzeImage, analyzeVideo, isVideoFile, fetchImageObjectUrl,
  createReport, generateReportPdf, openReportPdf, ocrVessel, checkBackendOnline, friendlyApiDetail,
} from '../lib/api'
import {
  applyVesselOcrToReport,
  isCoverOnlyResult,
} from '../lib/vesselCover'

const STEPS = [
  { id: 'images',    title: 'Upload Raw Data' },
  { id: 'vessel',    title: 'Vessel & Job' },
  { id: 'findings',  title: 'Inspection Findings' },
  { id: 'review',    title: 'Review & Generate' },
]

const REGIONS_WITH_DETAIL = ['Bilege_keels', 'Sea_chest', 'Propeller', 'Radder', 'Rope']

function formatVesselSummaryValue(key, value) {
  if (value == null || value === '') return '—'
  if (key === 'client' && typeof value === 'object') {
    const c = value
    return [c.company, c.contact_person].filter(Boolean).join(' · ') || '—'
  }
  if (key === 'crews' && Array.isArray(value)) {
    return value.map((c) => c.label || c.supervisor || 'Crew').filter(Boolean).join(', ') || '—'
  }
  if (key === 'client_reps' && Array.isArray(value)) {
    return value.map((r) => `${r.role || 'Rep'}: ${r.name || '—'}`).join('; ') || '—'
  }
  if (key === 'team' && Array.isArray(value)) {
    return value.map((m) => `${m.role || ''}: ${m.name || ''}`.trim()).filter(Boolean).join('; ') || '—'
  }
  if (typeof value === 'object') return '—'
  return String(value)
}

export default function NewReport() {
  const r = useReport()
  const nav = useNavigate()
  const [busy, setBusy] = useState(false)

  const onAnalyzeAll = async () => {
    setBusy(true)
    try {
      const tasks = []
      for (const region of HULL_REGIONS) {
        for (const img of r.images[region.id] || []) {
          if (img.status === 'done' || !img.file) continue
          r.updateImage(region.id, img.id, { status: 'analyzing' })
          tasks.push(
            analyzeImage(img.file)              // no region hint — let AI decide
              .then((result) => r.updateImage(region.id, img.id, {
                status: 'done', result, backendId: result.image_id,
              }))
              .catch(() => r.updateImage(region.id, img.id, { status: 'error' })),
          )
        }
      }
      await Promise.all(tasks)
      toast.success('All photos analysed')
    } finally { setBusy(false) }
  }

  const onGenerate = async () => {
    if (!r.vessel.vesselName) {
      toast.error('Please enter a vessel name first')
      return
    }
    if (!r.vesselImageId?.trim()) {
      toast.error(
        'Photographic Report cover is required — open Vessel & Job, re-detect the nameplate, then click "Use for report".',
      )
      r.setStep(1)
      return
    }
    setBusy(true)
    try {
      if (!(await checkBackendOnline())) {
        toast.error(
          'Backend is not running — start it on http://127.0.0.1:8000 before generating a PDF.',
          { duration: 8000 },
        )
        return
      }
      // 1. analyse anything that's still pending (no region hint — AI routes)
      const pending = []
      for (const region of HULL_REGIONS) {
        for (const img of r.images[region.id] || []) {
          if (img.status === 'done' || !img.file) continue
          r.updateImage(region.id, img.id, { status: 'analyzing' })
          pending.push(
            analyzeImage(img.file)
              .then((result) => r.updateImage(region.id, img.id, {
                status: 'done', result, backendId: result.image_id,
              })),
          )
        }
      }
      if (pending.length) {
        toast(`Analysing ${pending.length} photo(s)…`)
        await Promise.all(pending)
      }

      // 2. collect backend image ids
      const imageIds = []
      for (const region of HULL_REGIONS) {
        for (const img of r.images[region.id] || []) {
          if (img.backendId) imageIds.push(img.backendId)
        }
      }

      // 3. create the report — full payload (findings + vessel image)
      const report = await createReport({
        vessel: r.vessel,
        image_ids: imageIds,
        region_inspections: r.regionInspections,
        vessel_image_id: r.vesselImageId.trim(),
        client_id: r.clientId || null,
      })
      toast.success(`Report ${report.id} created`)

      // 4. build the PDF (can take several minutes on large batches)
      toast('Building PDF (fast mode — representative photos per section)…', { duration: 10000 })
      await generateReportPdf(report.id)
      toast.success('PDF generated')

      // 5. open PDF (separate step — build may succeed while download times out)
      try {
        await openReportPdf(report.id)
      } catch (openErr) {
        toast.error(
          `PDF saved but could not open in browser: ${openErr?.response?.data?.detail || openErr?.message || openErr}. Open it from Reports.`,
        )
        nav('/reports')
        return
      }

      r.reset()
      nav('/reports')
    } catch (e) {
      const raw = e?.response?.data?.detail || e?.message || String(e)
      const msg = friendlyApiDetail(
        typeof raw === 'string' ? raw : JSON.stringify(raw),
        'Report or PDF failed',
      )
      toast.error(`Failed: ${msg}`, { duration: 8000 })
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-brand-300">New Inspection</div>
          <h1 className="mt-1 font-display text-2xl font-bold text-white">Create Marine Service Report</h1>
          <p className="text-sm text-slate-400">Four quick steps — we'll do the rest.</p>
        </div>
        <button onClick={r.reset} className="btn-ghost text-xs">Reset</button>
      </header>

      <Stepper steps={STEPS} current={r.step} onJump={(i) => r.setStep(i)} />

      <AnimatePresence mode="wait">
        {r.step === 0 && (
          <motion.div key="s0" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
            <ImagesStep />
          </motion.div>
        )}
        {r.step === 1 && (
          <motion.div key="s1" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
            <VesselStep />
          </motion.div>
        )}
        {r.step === 2 && (
          <motion.div key="s2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
            <FindingsStep />
          </motion.div>
        )}
        {r.step === 3 && (
          <motion.div key="s3" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
            <ReviewStep busy={busy} onAnalyzeAll={onAnalyzeAll} onGenerate={onGenerate} />
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-center justify-between gap-3 pt-2">
        <button className="btn-ghost" disabled={r.step === 0} onClick={r.prev}>
          <ArrowLeft size={16} /> Back
        </button>
        {r.step < 3 ? (
          <button className="btn-primary" onClick={r.next}>
            Continue <ArrowRight size={16} />
          </button>
        ) : (
          <button className="btn-primary" disabled={busy} onClick={onGenerate}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <FileDown size={16} />}
            Generate PDF
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- Step 1 ----
function VesselStep() {
  const r = useReport()
  const { vessel, updateVessel, clientId, setClientFromDirectory, ensureVesselCover, vesselImageId } = r
  const set = (k) => (e) => updateVessel({ [k]: e.target.value })
  const hasName = Boolean((vessel.vesselName || '').trim())

  useEffect(() => {
    ensureVesselCover(true)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- panel re-OCRs cover image

  return (
    <div className="space-y-4">
      <PhotographicCoverPanel defaultOcrOpen={!hasName} />

      {/* CLIENT / VESSEL OWNER — picked from saved directory (one-time entry) */}
      <section className="glass rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <Building2 size={16} className="text-brand-300" />
          <h3 className="font-display font-semibold text-white">Client / Vessel Owner</h3>
          <span className="pill-brand text-[10px]">printed on every page</span>
        </div>
        <p className="text-xs text-slate-400 mb-3">
          Pick the client from your <span className="text-brand-300">Clients directory</span>.
          Add new ones once and they'll be reusable on every future inspection.
        </p>
        <ClientPicker value={clientId} onSelect={setClientFromDirectory} />
      </section>

      <section className="glass rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Anchor size={16} className="text-brand-300" />
          <h3 className="font-display font-semibold text-white">Vessel — General Information</h3>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Vessel Name"><input className="input" value={vessel.vesselName} onChange={set('vesselName')} placeholder="e.g. WOLVERINE" /></Field>
          <Field label="Job No.">    <input className="input" value={vessel.jobNo}      onChange={set('jobNo')}      placeholder="e.g. 2024-1557" /></Field>
          <Field label="Date of Dive"><input type="date" className="input" value={vessel.diveDate} onChange={set('diveDate')} /></Field>
          <Field label="Vessel Type">
            <select className="input" value={vessel.vesselType} onChange={set('vesselType')}>
              {VESSEL_TYPES.map((t) => <option key={t} className="bg-ink-900">{t}</option>)}
            </select>
          </Field>
          <Field label="Vessel Class">
            <select className="input" value={vessel.vesselClass} onChange={set('vesselClass')}>
              {VESSEL_CLASSES.map((t) => <option key={t} className="bg-ink-900">{t}</option>)}
            </select>
          </Field>
          <Field label="Location">   <input className="input" value={vessel.location} onChange={set('location')} placeholder="AESPA Anchorage" /></Field>
          <Field label="LOA (m)">    <input className="input" value={vessel.loa}      onChange={set('loa')}      placeholder="200" /></Field>
          <Field label="Draft (m)">  <input className="input" value={vessel.draft}    onChange={set('draft')}    placeholder="13.4" /></Field>
          <Field label="Vessel Captain"><input className="input" value={vessel.captain} onChange={set('captain')} placeholder="Capt. Paolo M." /></Field>
          <Field label="Job Scope" className="sm:col-span-2 lg:col-span-3">
            <input className="input" value={vessel.jobScope} onChange={set('jobScope')} />
          </Field>
          <Field label="Remarks / Notes" className="sm:col-span-2 lg:col-span-3">
            <textarea className="input" rows={2} value={vessel.notes || ''} onChange={set('notes')}
              placeholder="e.g. Vessel was at anchor, light current…" />
          </Field>
        </div>
      </section>

      {/* CLIENT REPRESENTATIVES — captain etc. shown at the top of the report */}
      <ClientRepresentativesSection />

      {/* DIVE CREWS — one or more, each with their own days + sea conditions */}
      <DiveCrewsSection />
    </div>
  )
}

// ----- Client Representatives -------------------------------------------
function ClientRepresentativesSection() {
  const r = useReport()
  const reps = r.vessel.client_reps || []
  return (
    <section className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ShieldCheck size={16} className="text-brand-300" />
          <h3 className="font-display font-semibold text-white">Client Representatives</h3>
          <span className="text-[11px] text-slate-400">on the vessel side</span>
        </div>
        <button type="button" onClick={() => r.addClientRep()} className="btn-outline text-xs">
          <Plus size={12} /> Add Representative
        </button>
      </div>
      {reps.length === 0 ? (
        <p className="text-sm text-slate-400">
          Add the vessel's Captain or other client-side contacts. They appear under
          <span className="text-brand-300"> CLIENT REPRESENTATIVES </span> on the report.
        </p>
      ) : (
        <div className="space-y-2">
          {reps.map((rep, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 items-end">
              <div className="col-span-4 sm:col-span-3">
                <span className="label">Role</span>
                <select className="input" value={rep.role || 'Captain'}
                        onChange={(e) => r.updateClientRep(i, { role: e.target.value })}>
                  {['Captain', 'Chief Officer', 'Chief Engineer', 'Owner Rep', 'Class Surveyor', 'Other']
                    .map((opt) => <option key={opt} className="bg-ink-900">{opt}</option>)}
                </select>
              </div>
              <div className="col-span-7 sm:col-span-8">
                <span className="label">Name</span>
                <input className="input" value={rep.name || ''}
                       onChange={(e) => r.updateClientRep(i, { name: e.target.value })}
                       placeholder="Lyndon Llanos" />
              </div>
              <div className="col-span-1 flex justify-end">
                <button type="button" onClick={() => r.removeClientRep(i)}
                        className="btn-ghost !px-2 text-rose-300"
                        title="Remove">
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// ----- Dive Crews container ---------------------------------------------
function DiveCrewsSection() {
  const r = useReport()
  const crews = r.vessel.crews || []
  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-brand-300">Dive Operations</div>
          <h2 className="font-display text-lg font-bold text-white">Diving Teams &amp; Schedule</h2>
          <p className="text-xs text-slate-400">
            Each team has its own supervisor, divers, sea conditions, and per-day timings.
            Add another team if a different crew dove on different days.
          </p>
        </div>
        <button type="button" onClick={() => r.addCrew()} className="btn-primary text-xs">
          <Plus size={12} /> Add Dive Team
        </button>
      </div>

      {crews.map((c, i) => (
        <CrewBlock key={i} idx={i} crew={c} canRemove={crews.length > 1} />
      ))}
    </section>
  )
}

function CrewBlock({ idx, crew, canRemove }) {
  const r = useReport()
  const [open, setOpen] = useState(true)
  const setCrew = (k) => (e) => r.updateCrew(idx, { [k]: e.target.value })
  const setSea  = (k) => (e) => r.updateCrewSea(idx, { [k]: e.target.value })
  return (
    <div className="glass rounded-2xl">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between p-5">
        <div className="flex items-center gap-2">
          {open ? <ChevronDown size={16} className="text-brand-300" /> : <ChevronRight size={16} className="text-brand-300" />}
          <Users size={16} className="text-brand-300" />
          <input
            className="bg-transparent font-display font-semibold text-white text-base outline-none focus:bg-white/[0.04] rounded px-1.5 py-0.5"
            value={crew.label || `Diving Team - ${idx + 1}`}
            onChange={setCrew('label')}
            onClick={(e) => e.stopPropagation()}
          />
          <span className="text-[11px] text-slate-400">
            ({(crew.days || []).length} day{(crew.days || []).length !== 1 ? 's' : ''})
          </span>
        </div>
        {canRemove && (
          <button type="button" onClick={(e) => { e.stopPropagation(); r.removeCrew(idx) }}
                  className="btn-ghost text-xs text-rose-300">
            <Trash2 size={12} /> Remove Team
          </button>
        )}
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-4">
          {/* Crew line-up */}
          <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-4 space-y-3">
            <div className="text-[11px] uppercase tracking-wider text-brand-300 font-semibold">Team Members</div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
              <Field label="Dive Supervisor">
                <input className="input" value={crew.supervisor || ''}
                       onChange={setCrew('supervisor')} placeholder="Fahmi" />
              </Field>
              <Field label="Boat Captain">
                <input className="input" value={crew.boat_captain || ''}
                       onChange={setCrew('boat_captain')} placeholder="Jabbar" />
              </Field>
              <Field label="Divers and Tenders" className="sm:col-span-2 lg:col-span-1">
                <input className="input" value={crew.divers || ''}
                       onChange={setCrew('divers')}
                       placeholder="Eugenio, Arivu, Khairul, Tamil, Faiz" />
              </Field>
            </div>
          </div>

          {/* Sea conditions for this crew */}
          <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-4 space-y-3">
            <div className="text-[11px] uppercase tracking-wider text-brand-300 font-semibold">Sea Conditions</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Field label="Weather">
                <input className="input" value={crew.sea?.weather || ''} onChange={setSea('weather')} placeholder="Sunny" />
              </Field>
              <Field label="Sea">
                <input className="input" value={crew.sea?.sea || ''} onChange={setSea('sea')} placeholder="Choppy" />
              </Field>
              <Field label="Visibility (m)">
                <input className="input" value={crew.sea?.visibility || ''} onChange={setSea('visibility')} placeholder="0.5" />
              </Field>
              <Field label="Tide (kn)">
                <input className="input" value={crew.sea?.tide || ''} onChange={setSea('tide')} placeholder="0.5" />
              </Field>
            </div>
          </div>

          {/* Per-day timings */}
          <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-[11px] uppercase tracking-wider text-brand-300 font-semibold">
                Time &amp; Duration of Job
              </div>
              <button type="button" onClick={() => r.addCrewDay(idx)} className="btn-outline text-xs">
                <Plus size={12} /> Add Day
              </button>
            </div>
            {(crew.days || []).map((d, dIdx) => (
              <DayBlock key={dIdx} idx={idx} dayIdx={dIdx} day={d}
                        canRemove={(crew.days || []).length > 1} />
            ))}
          </div>

          {/* Team-level remarks */}
          <Field label="Team Remarks">
            <textarea className="input" rows={2} value={crew.remarks || ''}
              onChange={setCrew('remarks')}
              placeholder="Standby due to strong tidal currents…" />
          </Field>
        </div>
      )}
    </div>
  )
}

function DayBlock({ idx, dayIdx, day, canRemove }) {
  const r = useReport()
  const set = (k) => (e) => r.updateCrewDay(idx, dayIdx, { [k]: e.target.value })
  return (
    <div className="rounded-lg bg-white/[0.02] ring-1 ring-white/5 p-3">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-sm font-bold text-white tracking-wider uppercase">Day {dayIdx + 1}</h4>
        <div className="flex items-center gap-2">
          <Field label="Date" className="!mb-0">
            <input type="date" className="input !py-1 !text-xs" value={day.date || ''} onChange={set('date')} />
          </Field>
          {canRemove && (
            <button type="button" onClick={() => r.removeCrewDay(idx, dayIdx)}
                    className="btn-ghost !px-2 text-rose-300" title="Remove day">
              <X size={12} />
            </button>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <Field label="Time Left Base">     <input type="time" className="input" value={day.time_left_base || ''}       onChange={set('time_left_base')} /></Field>
        <Field label="Arrived Job Site">   <input type="time" className="input" value={day.time_arrived_jobsite || ''} onChange={set('time_arrived_jobsite')} /></Field>
        <Field label="Dive Ops Started">   <input type="time" className="input" value={day.dive_ops_started || ''}     onChange={set('dive_ops_started')} /></Field>
        <Field label="Dive Ops Completed"> <input type="time" className="input" value={day.dive_ops_completed || ''}   onChange={set('dive_ops_completed')} /></Field>
        <Field label="Left Job Site">      <input type="time" className="input" value={day.time_left_jobsite || ''}    onChange={set('time_left_jobsite')} /></Field>
        <Field label="Arrived Base">       <input type="time" className="input" value={day.time_arrived_base || ''}    onChange={set('time_arrived_base')} /></Field>
        <Field label="Standby (From)">     <input type="time" className="input" value={day.standby_from || ''}         onChange={set('standby_from')} /></Field>
        <Field label="Standby (To)">       <input type="time" className="input" value={day.standby_to || ''}           onChange={set('standby_to')} /></Field>
        <Field label="Day Remarks" className="col-span-2 md:col-span-4">
          <input className="input" value={day.remarks || ''} onChange={set('remarks')}
                 placeholder="Standby due to weather, currents…" />
        </Field>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------- Step 2 ----
/**
 * Single auto-routing intake. The surveyor drops every photo / video / folder
 * from the dive and the AI sorts each into its hull region.  Manual region
 * selection only appears as an "override" once routing is done.
 */
// Cap how many image analyses run in parallel at the *client* level.
// HTTP/1.1 browsers serve ~6 sockets per origin and axios has a per-
// request timeout — without a cap, dropping 1000 photos would queue ~994
// requests inside the browser and the tail end would all time out long
// before the backend ever gets to them. Four is a sweet spot: the
// backend's `_ANALYZE_SEMAPHORE` (1 on CUDA by default) is the real
// bottleneck; we just need enough in-flight to keep it fed without
// piling up. Override via NAUTICAI_UI_PARALLEL on window if you ever
// want to push it.
const MAX_PARALLEL_IMAGES =
  Number(typeof window !== 'undefined' && window.NAUTICAI_UI_PARALLEL) || 6

function ImagesStep() {
  const r = useReport()
  const [staging, setStaging] = useState([])   // [{id, file, url, name, kind, status, error}]
  // Session totals power the live "Analysing X / Y (Z%)" chip — they
  // keep counting across staging cleanup so the chip doesn't reset when
  // an item leaves the queue.
  const [batchTotal, setBatchTotal] = useState(0)
  const [batchDone, setBatchDone] = useState(0)
  const [batchHull, setBatchHull] = useState(0)
  const [batchCover, setBatchCover] = useState(0)
  // Tracks ids currently processing. Lives in a ref so updates don't
  // cause renders; the auto-dispatch effect re-runs whenever `staging`
  // changes (item flips to analyzing/done/error), which is sufficient
  // to refill freed slots.
  const inFlightRef = useRef(new Set())
  const ocrAppliedRef = useRef(false)
  const ocrSweepRef = useRef([])       // fallback: largest images
  const ocrPriorityRef = useRef([])    // first + last uploads (common nameplate position)

  const trackForOcrSweep = (file) => {
    if (!file?.type?.startsWith('image/')) return
    const list = [...ocrSweepRef.current, file]
    list.sort((a, b) => (b.size || 0) - (a.size || 0))
    ocrSweepRef.current = list.slice(0, 8)
  }

  const trackOcrPriority = (files) => {
    const imgs = files.filter((f) => f?.type?.startsWith('image/'))
    if (!imgs.length) return
    const head = imgs.slice(0, 3)
    const tail = imgs.length > 3 ? imgs.slice(-3) : []
    const merged = [...head, ...tail]
    const seen = new Set()
    ocrPriorityRef.current = merged.filter((f) => {
      const k = f.name + f.size
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
  }

  const ocrSweepOrder = () => {
    const seen = new Set()
    const out = []
    for (const f of [...ocrPriorityRef.current, ...ocrSweepRef.current]) {
      const k = f.name + (f.size || 0)
      if (seen.has(k)) continue
      seen.add(k)
      out.push(f)
    }
    return out.slice(0, 12)
  }

  const finalizeBatchVesselOcr = async () => {
    const ok = await r.autoDetectVesselFromUpload()
    if (ok) return true
    const coverId = r.vesselImageId?.trim()
    if (coverId) {
      const synced = await r.syncVesselOcrFromServer(coverId, { refresh: true })
      return synced || r.ensureVesselCover(true)
    }
    for (const file of ocrSweepOrder().slice(0, 8)) {
      try {
        const ocr = await ocrVessel(file, { persist: true })
        r.pushOcrCandidate({ vessel_ocr: ocr, image_id: ocr.image_id })
      } catch { /* try next */ }
    }
    return r.autoDetectVesselFromUpload() || r.ensureVesselCover(true)
  }

  const considerVesselOcr = (result) => {
    if (isCoverOnlyResult(result) && result?.image_id) {
      r.applyCoverFromAnalyze(result)
      return
    }
    r.pushOcrCandidate(result)
  }

  const counts = useMemo(() => {
    let imgs = 0, frames = 0, videos = 0
    for (const region of HULL_REGIONS) {
      for (const item of r.images[region.id] || []) {
        if (item.kind === 'frame') frames++
        else imgs++
      }
    }
    for (const s of staging) if (s.kind === 'video') videos++
    return { imgs, frames, videos, staged: staging.length }
  }, [r.images, staging])

  // Reset the session counter once the queue fully drains (and nothing
  // is in flight) — gives the user a clean "0 / 0" between batches.
  useEffect(() => {
    if (staging.length === 0 && batchDone >= batchTotal && batchTotal > 0) {
      ;(async () => {
        if (!ocrAppliedRef.current) {
          const ok = await finalizeBatchVesselOcr()
          if (ok) {
            ocrAppliedRef.current = true
            const name = r.vessel.vesselName
            const conf = r.vesselOcrConfidence
            toast.success(
              `Vessel ${name} (${(conf * 100).toFixed(0)}% OCR) — name & cover linked`,
            )
          }
        }
      })()
      const t = setTimeout(() => {
        setBatchTotal(0)
        setBatchDone(0)
        setBatchHull(0)
        setBatchCover(0)
      }, 4000)
      return () => clearTimeout(t)
    }
  }, [staging.length, batchDone, batchTotal])

  useEffect(() => {
    if (batchTotal === 0) {
      ocrAppliedRef.current = false
      ocrSweepRef.current = []
      ocrPriorityRef.current = []
    }
  }, [batchTotal])

  const addFiles = (files) => {
    trackOcrPriority(files)
    files.forEach(trackForOcrSweep)
    const next = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      url: URL.createObjectURL(file),
      name: file.name,
      size: file.size,
      kind: isVideoFile(file) ? 'video' : 'image',
      status: 'pending',          // 'pending' | 'analyzing' | 'done' | 'error'
      progress: 0,
      error: null,
    }))
    setStaging((p) => [...next, ...p])
    setBatchTotal((n) => n + next.length)
  }

  const removeStaged = (id) =>
    setStaging((p) => {
      const item = p.find((x) => x.id === id)
      if (!item) return p
      if (item.url) try { URL.revokeObjectURL(item.url) } catch { /* noop */ }
      // Shrink the batch total only when the item never finished —
      // completed items already moved batchDone forward.
      if (item.status !== 'done') {
        setBatchTotal((n) => Math.max(0, n - 1))
      }
      // A slot held by an in-flight request stays held until processOne's
      // finally runs (it'll see the item is gone and exit cleanly).
      return p.filter((x) => x.id !== id)
    })

  const processOne = async (id) => {
    const it = staging.find((x) => x.id === id)
    if (!it) return
    setStaging((p) => p.map((x) => x.id === id ? { ...x, status: 'analyzing', progress: 0, error: null } : x))

    try {
      if (it.kind === 'image') {
        const result = await analyzeImage(it.file)
        considerVesselOcr(result)
        // Cover / whole-ship / nameplate → Photographic Report OCR (not hull grids).
        if (isCoverOnlyResult(result)) {
          setBatchCover((n) => n + 1)
        } else {
          setBatchHull((n) => n + 1)
          r.addAnalyzedImage(result.region.id, {
            file: it.file,
            url: it.url,
            name: it.name,
            size: it.size,
            result,
            backendId: result.image_id,
            kind: 'image',
          })
        }
      } else {
        // VIDEO
        const data = await analyzeVideo(it.file, {
          strideSec: 2.0, maxFrames: 24,
          onProgress: (frac) =>
            setStaging((p) => p.map((x) => x.id === id ? { ...x, progress: frac } : x)),
        })
        // Fetch each frame thumb (auth-protected) and add to its predicted region.
        const thumbs = await Promise.all(
          data.frames.map((f) => fetchImageObjectUrl(f.image_id)),
        )
        data.frames.forEach((f, i) => {
          if (isCoverOnlyResult(f)) {
            considerVesselOcr(f)
            return
          }
          r.addAnalyzedImage(f.region.id, {
            url: thumbs[i],
            name: `${it.name} · t=${f.ts_sec.toFixed(1)}s`,
            result: f,
            backendId: f.image_id,
            kind: 'frame',
            ts_sec: f.ts_sec,
            source_filename: it.name,
          })
        })
        if (isCoverOnlyResult(data)) considerVesselOcr(data)
      }
      setStaging((p) => p.filter((x) => x.id !== id))  // success → remove from staging
      setBatchDone((n) => n + 1)
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || 'Analysis failed'
      setStaging((p) => p.map((x) => x.id === id ? { ...x, status: 'error', error: msg } : x))
      toast.error(`${it.name}: ${msg}`)
    } finally {
      // Free the slot so the auto-dispatch effect can pull the next pending.
      inFlightRef.current.delete(id)
    }
  }

  // User-facing retry: just flip the item back to 'pending' and let the
  // auto-dispatch effect pick it up under the concurrency cap. Avoids
  // calling processOne directly (which would bypass the cap).
  const queueForRetry = (id) =>
    setStaging((p) => p.map((x) => x.id === id ? { ...x, status: 'pending', error: null } : x))

  // Mass-retry: flip every failed item back to pending. The auto-dispatch
  // effect handles the actual re-runs under the concurrency cap.
  const retryAllFailed = () => {
    setStaging((p) => p.map((x) =>
      x.status === 'error' ? { ...x, status: 'pending', error: null } : x,
    ))
  }

  // Auto-dispatch analysis as soon as files land in staging — the
  // surveyor never has to click a button. Images run up to
  // MAX_PARALLEL_IMAGES at a time so we don't flood the browser's
  // socket pool (HTTP/1.1 caps at ~6 per origin) and trigger axios
  // timeouts on a long tail of queued requests; videos still run one
  // at a time. The effect re-fires whenever `staging` changes (item
  // flips status, completes, or fails) which is exactly when a slot
  // might have just been freed.
  useEffect(() => {
    const inFlight = inFlightRef.current
    // Count images currently in flight (videos take a separate slot).
    let imagesInFlight = 0
    let videoInFlight = false
    for (const id of inFlight) {
      const it = staging.find((s) => s.id === id)
      if (!it) continue
      if (it.kind === 'image') imagesInFlight += 1
      else if (it.kind === 'video') videoInFlight = true
    }
    let slots = MAX_PARALLEL_IMAGES - imagesInFlight
    for (const s of staging) {
      if (slots <= 0) break
      if (s.kind !== 'image' || s.status !== 'pending') continue
      if (inFlight.has(s.id)) continue
      inFlight.add(s.id)
      slots -= 1
      processOne(s.id)   // fire & forget; finally releases the slot
    }
    if (!videoInFlight) {
      const nextVideo = staging.find((s) =>
        s.kind === 'video' && s.status === 'pending' && !inFlight.has(s.id),
      )
      if (nextVideo) {
        inFlight.add(nextVideo.id)
        processOne(nextVideo.id)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [staging])

  const routedRegions = HULL_REGIONS
    .map((reg) => ({ region: reg, items: r.images[reg.id] || [] }))
    .filter((g) => g.items.length > 0)

  // Live progress numbers for the chip in the header. `batchDone` only
  // counts successes; in-flight + pending live in `staging`.
  const progressPct = batchTotal > 0 ? Math.round((batchDone / batchTotal) * 100) : 0
  const showProgress = batchTotal > 0 && (staging.length > 0 || batchDone < batchTotal)

  return (
    <div className="space-y-5">
      {/* Header banner */}
      <div className="glass rounded-2xl p-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-brand-400/15 ring-1 ring-brand-400/30 p-2">
            <Wand2 size={18} className="text-brand-300" />
          </div>
          <div>
            <h3 className="font-display font-semibold text-white">Drop everything from the dive</h3>
            <p className="text-sm text-slate-400 max-w-2xl">
              Drop the full dive folder. Models route hull vs cover; OCR links the vessel name
              and Photographic Report photo. On any hull photo, hover and click the image icon
              to set the PDF cover, or use Re-detect on step 2 (Vessel & Job).
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          {showProgress && (
            <span className="pill-brand inline-flex items-center gap-1.5">
              <Loader2 size={10} className={staging.length ? 'animate-spin' : 'opacity-40'} />
              Analysing {batchDone} / {batchTotal} ({progressPct}%)
            </span>
          )}
          {batchHull > 0 && (
            <span className="pill-mute">{batchHull} hull · {batchCover} cover</span>
          )}
          {counts.imgs > 0 && batchHull === 0 && (
            <span className="pill-mute">{counts.imgs} hull photos routed</span>
          )}
          {counts.imgs > 0 && batchHull > 0 && (
            <span className="pill-mute">{counts.imgs} in grids</span>
          )}
          {counts.frames > 0 && <span className="pill-mute"><Film size={10} /> {counts.frames} frames</span>}
          {counts.staged > 0 && <span className="pill-warn">{counts.staged} in queue</span>}
        </div>
      </div>

      {showProgress && (
        <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-2.5">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full rounded-full bg-gradient-to-r from-brand-300 to-accent-400 transition-[width] duration-300"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="mt-1.5 flex items-center justify-between text-[11px] text-slate-400">
            <span>
              {staging.length > 0
                ? <>Background analysis &mdash; feel free to move on to the next step.</>
                : <>All photos processed.</>}
            </span>
            <span className="font-mono text-slate-300">
              {batchDone} / {batchTotal}
              {batchDone > 0 && (
                <> · {batchHull} hull · {batchCover} cover</>
              )}
            </span>
          </div>
        </div>
      )}

      <ImageDropzone onFiles={addFiles}
        hint="Drop photos, an ROV video, or the entire dive-day folder — AI will route everything" />

      {/* Staging / processing list */}
      {staging.length > 0 && (
        <section className="glass rounded-2xl p-5">
          <header className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Sparkles size={16} className="text-brand-300" />
              <h3 className="font-display font-semibold text-white">Processing</h3>
              <span className="pill-mute">{staging.length}</span>
            </div>
            {staging.some((s) => s.status === 'error') && (
              <button className="btn-outline text-xs" onClick={retryAllFailed}>
                <Wand2 size={12} /> Retry failed
              </button>
            )}
          </header>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {staging.map((s) => (
              <StagedCard key={s.id} item={s} onRemove={() => removeStaged(s.id)}
                          onAnalyse={() => queueForRetry(s.id)} />
            ))}
          </div>
        </section>
      )}

      {/* Routed results — one section per region */}
      {routedRegions.length > 0 ? routedRegions.map(({ region, items }) => (
        <RoutedRegion key={region.id} region={region} items={items} />
      )) : (
        <div className="glass rounded-2xl p-8 text-center text-sm text-slate-400">
          Once you drop photos or a video above, they will appear here grouped by hull region.
        </div>
      )}
    </div>
  )
}

function StagedCard({ item, onRemove, onAnalyse }) {
  const pct = Math.round((item.progress || 0) * 100)
  const isVideo = item.kind === 'video'
  return (
    <div className="rounded-xl ring-1 ring-white/10 bg-white/[0.03] overflow-hidden">
      <div className="relative aspect-square bg-black">
        {isVideo
          ? <video src={item.url} muted className="h-full w-full object-cover" />
          : <img   src={item.url} className="h-full w-full object-cover" alt={item.name} />}
        {item.status === 'analyzing' && (
          <div className="absolute inset-0 bg-black/55 grid place-items-center text-center">
            <div className="space-y-1">
              <Loader2 size={18} className="animate-spin text-brand-300 mx-auto" />
              <div className="text-[10px] text-white">
                {isVideo && pct < 100 ? `Uploading ${pct}%` : 'Analysing…'}
              </div>
            </div>
          </div>
        )}
        {isVideo && (
          <div className="absolute left-2 top-2">
            <span className="pill-brand text-[10px]"><Video size={9} /> video</span>
          </div>
        )}
        <button onClick={onRemove}
                className="absolute right-1.5 top-1.5 rounded-md bg-ink-900/80 p-1 text-rose-300 hover:bg-ink-800">
          <X size={12} />
        </button>
      </div>
      <div className="p-2.5">
        <div className="text-[11px] font-semibold text-white truncate">{item.name}</div>
        {item.status === 'error' && (
          <div className="mt-1 flex items-center gap-1 text-[10px] text-rose-300">
            <AlertTriangle size={10} /> {item.error}
          </div>
        )}
        {(item.status === 'pending' || item.status === 'error') && (
          <button onClick={onAnalyse} className="btn-outline text-[11px] mt-2 w-full">
            <Sparkles size={11} /> {item.status === 'error' ? 'Retry' : 'Run'}
          </button>
        )}
      </div>
    </div>
  )
}

function RoutedRegion({ region, items }) {
  const r = useReport()
  const [open, setOpen] = useState(true)
  const avg = items.length
    ? items.reduce((s, i) => s + (i.result?.fouling_pct || 0), 0) / items.length
    : 0
  const frames = items.filter((i) => i.kind === 'frame').length

  return (
    <section className="glass rounded-2xl">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between p-4">
        <div className="flex items-center gap-3 flex-wrap">
          {open ? <ChevronDown size={16} className="text-brand-300" /> : <ChevronRight size={16} className="text-brand-300" />}
          <h3 className="font-display font-semibold text-white">{region.displayLabel}</h3>
          <span className="pill-mute">{items.length} item{items.length !== 1 && 's'}</span>
          {frames > 0 && <span className="pill-mute"><Film size={10} /> {frames} from video</span>}
          <span className="pill-brand">~{avg.toFixed(0)}% fouled</span>
        </div>
      </button>
      {open && (
        <div className="px-4 pb-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
            {items.map((img) => (
              <RoutedCard key={img.id} item={img} region={region}
                onRemove={() => r.removeImage(region.id, img.id)}
                onMove={(to) => r.moveImage(region.id, img.id, to)} />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function RoutedCard({ item, region, onRemove, onMove }) {
  const r = useReport()
  const [override, setOverride] = useState(false)
  const isReportCover = Boolean(item.backendId && r.vesselImageId === item.backendId)

  const useAsCover = async (removeFromRegion = false) => {
    if (!item.backendId) {
      toast.error('This photo has no backend id yet — wait for analysis.')
      return
    }
    if (item.result?.vessel_ocr) {
      r.pushOcrCandidate({ image_id: item.backendId, vessel_ocr: item.result.vessel_ocr })
    }
    r.setVesselImageId(item.backendId)
    await r.syncVesselOcrFromServer(item.backendId, { refresh: true })
    if (removeFromRegion) {
      r.removeImage(region.id, item.id)
    }
    setOverride(false)
    const name = (r.vessel.vesselName || '').trim()
    toast.success(
      name
        ? `Photographic cover: ${name}`
        : 'Photographic Report will use this photo on the cover page.',
    )
  }

  return (
    <div className={`group relative overflow-hidden rounded-xl border bg-ink-900 transition ${
      isReportCover ? 'border-brand-400/60 ring-1 ring-brand-400/30' : 'border-white/10'
    }`}>
      <img src={item.url} alt={item.name}
           className="aspect-square w-full object-cover transition group-hover:scale-105" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink-950 via-ink-950/40 to-transparent" />

      {isReportCover && (
        <div className="absolute left-2 top-2 z-[1]">
          <span className="pill-brand text-[10px]"><ImageIcon size={9} /> PDF cover</span>
        </div>
      )}
      {item.kind === 'frame' && !isReportCover && (
        <div className="absolute left-2 top-2">
          <span className="pill-brand text-[10px]"><Film size={9} /> frame</span>
        </div>
      )}
      <div className="absolute right-2 top-2 flex gap-1 opacity-0 transition group-hover:opacity-100">
        <button
          type="button"
          onClick={() => useAsCover(false)}
          className="rounded-lg bg-ink-900/80 p-1.5 text-emerald-300 hover:bg-ink-800"
          title="Use as Photographic Report cover (keeps photo in this region)">
          <ImageIcon size={13} />
        </button>
        <button onClick={() => setOverride((v) => !v)}
                className="rounded-lg bg-ink-900/80 p-1.5 text-brand-300 hover:bg-ink-800"
                title="Move region or remove from grid for cover">
          <Wand2 size={13} />
        </button>
        <button onClick={onRemove}
                className="rounded-lg bg-ink-900/80 p-1.5 text-rose-300 hover:bg-ink-800"
                title="Remove">
          <Trash2 size={13} />
        </button>
      </div>

      {override && (
        <div className="absolute inset-0 grid place-items-center bg-ink-950/85 p-2 z-10">
          <div className="w-full space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-brand-300 font-semibold">Move to…</div>
            <select className="input text-xs" defaultValue=""
                    onChange={(e) => { if (e.target.value) { onMove(e.target.value); setOverride(false) } }}>
              <option value="" className="bg-ink-900">— Pick region —</option>
              {HULL_REGIONS.filter((r) => r.id !== region.id).map((r) => (
                <option key={r.id} value={r.id} className="bg-ink-900">{r.displayLabel}</option>
              ))}
            </select>
            <button type="button" onClick={() => useAsCover(false)}
                    className="btn-outline text-[10px] w-full inline-flex items-center justify-center gap-1">
              <ImageIcon size={11} /> Set as PDF cover (keep in region)
            </button>
            <button type="button" onClick={() => useAsCover(true)}
                    className="btn-ghost text-[10px] w-full inline-flex items-center justify-center gap-1 text-slate-300">
              <ImageIcon size={11} /> Set as PDF cover only (remove from grid)
            </button>
            <button onClick={() => setOverride(false)} className="btn-ghost text-[10px] w-full">Cancel</button>
          </div>
        </div>
      )}

      <div className="absolute inset-x-0 bottom-0 p-2 text-[10px]">
        <div className="truncate font-semibold text-white">{item.name}</div>
        <div className="mt-1 flex flex-wrap gap-1">
          {item.result && (
            <>
              <span className="pill-mute">
                {item.result.cover_only || item.result.stage?.id === 'not_hull'
                  ? 'cover'
                  : item.result.stage?.id}
              </span>
              <span className="pill-warn">{Math.round(item.result.fouling_pct)}%</span>
              <span className="pill-brand">{item.result.species?.top_display || item.result.species?.top}</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- Step 3 ----
function FindingsStep() {
  const r = useReport()
  const regions = HULL_REGIONS.filter((reg) => (r.images[reg.id] || []).length > 0)
  if (regions.length === 0) {
    return (
      <div className="glass rounded-2xl p-8 text-center text-slate-400">
        <ClipboardCheck size={28} className="mx-auto text-brand-300/70 mb-2" />
        Add photos in the previous step. Inspection findings appear here so you can
        confirm what the AI saw and add manual entries (damage, anodes, propeller details…).
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <PhotographicCoverPanel compact />
      <div className="glass rounded-2xl p-4 text-sm text-slate-300">
        <span className="text-brand-300 font-semibold">Tip:</span> The AI fills the fouling
        section automatically. Use the form below to add the surveyor's manual notes (damage,
        anodes, propeller details, etc.). These appear with checkboxes in the final PDF.
      </div>
      {regions.map((region) => (
        <RegionFindings key={region.id} region={region} />
      ))}
    </div>
  )
}

function RegionFindings({ region }) {
  const r = useReport()
  const findings = r.regionInspections[region.id] || emptyFindings()
  const [open, setOpen] = useState(false)
  const update = (patch) => r.updateFinding(region.id, patch)
  const items = r.images[region.id] || []
  const done = items.filter((i) => i.status === 'done')
  const avg = done.length
    ? done.reduce((s, i) => s + (i.result?.fouling_pct || 0), 0) / done.length
    : 0

  return (
    <div className="glass rounded-2xl">
      <button type="button" onClick={() => setOpen((v) => !v)}
              className="w-full flex items-center justify-between p-5">
        <div className="flex items-center gap-3">
          {open ? <ChevronDown size={16} className="text-brand-300" /> : <ChevronRight size={16} className="text-brand-300" />}
          <h3 className="font-display font-semibold text-white">{region.displayLabel}</h3>
          <span className="pill-mute">{items.length} photo{items.length !== 1 && 's'}</span>
          <span className="pill-brand">Coverage {avg.toFixed(0)}%</span>
        </div>
        <span className={`pill-${findings.damage_observed ? 'warn' : 'mute'}`}>
          Damage: {findings.damage_observed ? 'Yes' : 'No'}
        </span>
      </button>
      {open && (
        <div className="px-5 pb-5 space-y-4">
          <CommonFindingsForm findings={findings} update={update} />
          {REGIONS_WITH_DETAIL.includes(region.id) && (
            <SpecificFindingsForm region={region} findings={findings}
              updateSub={(blockKey, patch) => r.updateFindingSubblock(region.id, blockKey, patch)} />
          )}
        </div>
      )}
    </div>
  )
}

function CheckboxRow({ label, value, onChange }) {
  return (
    <button type="button" onClick={() => onChange(!value)}
      className="flex items-center gap-2 rounded-lg bg-white/[0.03] hover:bg-white/[0.06] ring-1 ring-white/10 px-3 py-2 text-left transition">
      <span className={`grid place-items-center h-4 w-4 rounded ring-1 ${value ? 'bg-brand-500 ring-brand-400' : 'bg-transparent ring-white/30'}`}>
        {value && <span className="text-white text-[10px] leading-none">✓</span>}
      </span>
      <span className="text-xs text-slate-200">{label}</span>
    </button>
  )
}

function YesNoToggle({ label, value, onChange }) {
  return (
    <div className="rounded-lg bg-white/[0.03] ring-1 ring-white/10 p-3">
      <div className="text-[11px] uppercase tracking-wider text-slate-400 mb-2">{label}</div>
      <div className="flex gap-2">
        <button type="button" onClick={() => onChange(true)}
          className={`flex-1 py-1.5 rounded text-xs font-semibold transition ${value ? 'bg-emerald-500/80 text-white' : 'bg-white/5 text-slate-300'}`}>Yes</button>
        <button type="button" onClick={() => onChange(false)}
          className={`flex-1 py-1.5 rounded text-xs font-semibold transition ${!value ? 'bg-rose-500/70 text-white' : 'bg-white/5 text-slate-300'}`}>No</button>
      </div>
    </div>
  )
}

function CommonFindingsForm({ findings, update }) {
  return (
    <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-3">
      <div className="rounded-lg bg-white/[0.03] ring-1 ring-white/10 p-3">
        <div className="text-[11px] uppercase tracking-wider text-slate-400 mb-2">Overall Condition</div>
        <div className="flex gap-2">
          {['Good', 'Poor'].map((opt) => (
            <button key={opt} type="button" onClick={() => update({ overall_condition: opt })}
              className={`flex-1 py-1.5 rounded text-xs font-semibold transition ${findings.overall_condition === opt ? 'bg-brand-500 text-white' : 'bg-white/5 text-slate-300'}`}>
              {opt}
            </button>
          ))}
        </div>
      </div>
      <YesNoToggle label="Any Damage Observed?" value={findings.damage_observed}
        onChange={(v) => update({ damage_observed: v })} />
      <label className="block md:col-span-2">
        <span className="label">Damage / Surveyor Notes</span>
        <textarea className="input" rows={2} value={findings.notes || ''}
          onChange={(e) => update({ notes: e.target.value })}
          placeholder="Describe any anomalies, dents, paint loss, etc." />
      </label>
    </div>
  )
}

function SpecificFindingsForm({ region, findings, updateSub }) {
  const id = region.id
  if (id === 'Bilege_keels') {
    const b = findings.bilge_keels || {}
    return (
      <Subsection title="Bilge Keels — Additional Details">
        <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-3">
          <Field label="Port — Sections"><input className="input" value={b.port_sections || ''} onChange={(e) => updateSub('bilge_keels', { port_sections: e.target.value })} /></Field>
          <YesNoToggle label="Port Anodes?" value={!!b.port_anodes} onChange={(v) => updateSub('bilge_keels', { port_anodes: v })} />
          <Field label="Port Anode Depletion"><input className="input" value={b.port_depletion || ''} onChange={(e) => updateSub('bilge_keels', { port_depletion: e.target.value })} placeholder="e.g. 20%" /></Field>
          <Field label="Stbd — Sections"><input className="input" value={b.stbd_sections || ''} onChange={(e) => updateSub('bilge_keels', { stbd_sections: e.target.value })} /></Field>
          <YesNoToggle label="Stbd Anodes?" value={!!b.stbd_anodes} onChange={(v) => updateSub('bilge_keels', { stbd_anodes: v })} />
          <Field label="Stbd Anode Depletion"><input className="input" value={b.stbd_depletion || ''} onChange={(e) => updateSub('bilge_keels', { stbd_depletion: e.target.value })} placeholder="e.g. 20%" /></Field>
        </div>
      </Subsection>
    )
  }
  if (id === 'Sea_chest') {
    const s = findings.sea_chest || {}
    return (
      <Subsection title="Sea Chest — Additional Details">
        <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-3">
          <Field label="Port High — Units"><input className="input" value={s.port_high_units || ''} onChange={(e) => updateSub('sea_chest', { port_high_units: e.target.value })} /></Field>
          <Field label="Port Low — Units"><input className="input" value={s.port_low_units || ''} onChange={(e) => updateSub('sea_chest', { port_low_units: e.target.value })} /></Field>
          <Field label="Stbd High — Units"><input className="input" value={s.stbd_high_units || ''} onChange={(e) => updateSub('sea_chest', { stbd_high_units: e.target.value })} /></Field>
          <Field label="Stbd Low — Units"><input className="input" value={s.stbd_low_units || ''} onChange={(e) => updateSub('sea_chest', { stbd_low_units: e.target.value })} /></Field>
          <YesNoToggle label="Gratings Intact?" value={s.gratings_intact !== false} onChange={(v) => updateSub('sea_chest', { gratings_intact: v })} />
          <YesNoToggle label="Abnormalities?" value={!!s.abnormalities} onChange={(v) => updateSub('sea_chest', { abnormalities: v })} />
        </div>
      </Subsection>
    )
  }
  if (id === 'Propeller') {
    const p = findings.propeller || {}
    return (
      <Subsection title="Propeller — Additional Details">
        <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-3">
          <Field label="No. of Propellers"><input className="input" value={p.count || ''} onChange={(e) => updateSub('propeller', { count: e.target.value })} /></Field>
          <Field label="Blades each"><input className="input" value={p.blade_count || ''} onChange={(e) => updateSub('propeller', { blade_count: e.target.value })} /></Field>
          <Field label="Diameter (mm)"><input className="input" value={p.diameter || ''} onChange={(e) => updateSub('propeller', { diameter: e.target.value })} /></Field>
          <Field label="Blade Type">
            <select className="input" value={p.blade_type || 'Fixed'} onChange={(e) => updateSub('propeller', { blade_type: e.target.value })}>
              {['Fixed', 'Silicon coated', 'Boss Cap Fins', 'Kurt Nozzle'].map((t) => <option key={t} className="bg-ink-900">{t}</option>)}
            </select>
          </Field>
          <Field label="Before Polish: Oxidised %"><input className="input" value={p.oxidised_pct || ''} onChange={(e) => updateSub('propeller', { oxidised_pct: e.target.value })} placeholder="e.g. 75" /></Field>
          <Field label="After Polish: Rubert Scale">
            <select className="input" value={p.rubert_scale || 'A'} onChange={(e) => updateSub('propeller', { rubert_scale: e.target.value })}>
              {['A', 'B', 'C', 'D', 'E', 'F'].map((t) => <option key={t} className="bg-ink-900">{t}</option>)}
            </select>
          </Field>
        </div>
        <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-2 mt-3">
          {[
            ['Pitting',            'pitting'],
            ['Cavitation',         'cavitation'],
            ['Cracks',             'cracks'],
            ['Previous Repairs',   'previous_repairs'],
            ['Cement Covers Intact','cement_covers_intact', true],
            ['Bolts Intact',       'bolts_intact',          true],
            ['Cone Bolt Intact',   'cone_bolt_intact',      true],
          ].map(([label, key, def]) => (
            <YesNoToggle key={key} label={label}
              value={p[key] !== undefined ? !!p[key] : !!def}
              onChange={(v) => updateSub('propeller', { [key]: v })} />
          ))}
        </div>
      </Subsection>
    )
  }
  if (id === 'Radder') {
    const rd = findings.rudder || {}
    return (
      <Subsection title="Rudder — Additional Details">
        <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-3">
          <Field label="No. of Rudders"><input className="input" value={rd.count || ''} onChange={(e) => updateSub('rudder', { count: e.target.value })} /></Field>
          <Field label="Rudder Type">
            <select className="input" value={rd.type || 'Hanging'} onChange={(e) => updateSub('rudder', { type: e.target.value })}>
              {['Hanging', 'Semi-Balanced', 'Balanced', 'Spade'].map((t) => <option key={t} className="bg-ink-900">{t}</option>)}
            </select>
          </Field>
          <YesNoToggle label="Plug(s) Intact?" value={rd.plug_intact !== false} onChange={(v) => updateSub('rudder', { plug_intact: v })} />
          <YesNoToggle label="Anodes Present?" value={rd.anodes !== false} onChange={(v) => updateSub('rudder', { anodes: v })} />
          <Field label="Anode Depletion"><input className="input" value={rd.depletion || ''} onChange={(e) => updateSub('rudder', { depletion: e.target.value })} placeholder="e.g. 25%" /></Field>
        </div>
      </Subsection>
    )
  }
  if (id === 'Rope') {
    const g = findings.rope_guard || {}
    return (
      <Subsection title="Rope Guard — Additional Details">
        <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-3">
          <Field label="Fitting">
            <select className="input" value={g.fitting || 'Welded'} onChange={(e) => updateSub('rope_guard', { fitting: e.target.value })}>
              {['Welded', 'Bolted'].map((t) => <option key={t} className="bg-ink-900">{t}</option>)}
            </select>
          </Field>
          <Field label="Rope Cutters">
            <select className="input" value={g.rope_cutters || 'No rope cutters'} onChange={(e) => updateSub('rope_guard', { rope_cutters: e.target.value })}>
              {['Intact', 'Missing', 'No rope cutters'].map((t) => <option key={t} className="bg-ink-900">{t}</option>)}
            </select>
          </Field>
          <YesNoToggle label="Inspection Window?" value={g.inspection_window !== false} onChange={(v) => updateSub('rope_guard', { inspection_window: v })} />
          <YesNoToggle label="Oil Leakage?" value={!!g.oil_leakage} onChange={(v) => updateSub('rope_guard', { oil_leakage: v })} />
          <YesNoToggle label="Rope Entanglement?" value={!!g.rope_entanglement} onChange={(v) => updateSub('rope_guard', { rope_entanglement: v })} />
          <YesNoToggle label="Entanglement Removed?" value={!!g.entanglement_removed} onChange={(v) => updateSub('rope_guard', { entanglement_removed: v })} />
        </div>
      </Subsection>
    )
  }
  return null
}

function Subsection({ title, children }) {
  return (
    <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-4">
      <div className="text-xs uppercase tracking-wider text-brand-300 font-semibold mb-3">{title}</div>
      {children}
    </div>
  )
}

// ---------------------------------------------------------------- Step 4 ----
function ReviewStep({ busy, onAnalyzeAll, onGenerate }) {
  const r = useReport()
  const totals = HULL_REGIONS.map((region) => {
    const items = r.images[region.id] || []
    const done = items.filter((i) => i.status === 'done')
    const hullDone = done.filter(
      (i) => !i.result?.cover_only && i.result?.stage?.id !== 'not_hull',
    )
    const before = hullDone.filter((i) => i.result?.stage?.id === 'before')
    const after  = hullDone.filter((i) => i.result?.stage?.id === 'after')
    const cover  = done.filter(
      (i) => i.result?.cover_only || i.result?.stage?.id === 'not_hull',
    )
    const avg = done.length
      ? done.reduce((s, i) => s + (i.result?.fouling_pct || 0), 0) / done.length
      : 0
    const findings = r.regionInspections[region.id]
    return { region, items, done, hullDone, before, after, cover, avg, findings }
  }).filter((t) => t.items.length)

  return (
    <div className="space-y-4">
      <PhotographicCoverPanel compact />

      <div className="grid lg:grid-cols-3 gap-4">
      <div className="glass rounded-2xl p-5 lg:col-span-2">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-display font-semibold text-white flex items-center gap-2">
            <ListChecks size={16} className="text-brand-300" /> Per-Region Summary
          </h3>
          <button className="btn-outline text-xs" onClick={onAnalyzeAll} disabled={busy}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Analyse all unprocessed
          </button>
        </div>
        <div className="mt-4 overflow-hidden rounded-xl border border-white/10">
          <table className="w-full text-sm">
            <thead className="bg-white/[0.03] text-[11px] uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3 text-left">Region</th>
                <th className="px-4 py-3 text-right">Photos</th>
                <th className="px-4 py-3 text-right">Before / After</th>
                <th className="px-4 py-3 text-right">Coverage %</th>
                <th className="px-4 py-3 text-right">Damage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {totals.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No photos uploaded yet.
                </td></tr>
              )}
              {totals.map((t) => (
                <tr key={t.region.id}>
                  <td className="px-4 py-3 text-white">{t.region.displayLabel}</td>
                  <td className="px-4 py-3 text-right">{t.items.length}</td>
                  <td className="px-4 py-3 text-right text-slate-300">
                    <span className="pill-mute mr-1">B {t.before.length}</span>
                    <span className="pill-brand">A {t.after.length}</span>
                  </td>
                  <td className="px-4 py-3 text-right">{t.avg.toFixed(0)}%</td>
                  <td className="px-4 py-3 text-right">
                    <span className={`pill-${t.findings?.damage_observed ? 'warn' : 'mute'}`}>
                      {t.findings?.damage_observed ? 'Yes' : '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="glass rounded-2xl p-5">
        <h3 className="font-display font-semibold text-white">Vessel Summary</h3>
        <dl className="mt-3 space-y-2 text-sm">
          {Object.entries(r.vessel)
            .filter(([k, v]) => k !== 'extra' && v !== '' && v != null
              && !(Array.isArray(v) && v.length === 0))
            .map(([k, v]) => (
              <div key={k} className="flex items-start justify-between gap-3 border-b border-white/5 pb-2 last:border-none">
                <dt className="text-xs uppercase tracking-wider text-slate-400">
                  {k.replace(/_/g, ' ')}
                </dt>
                <dd className="text-right text-slate-200 max-w-[55%] break-words">
                  {formatVesselSummaryValue(k, v)}
                </dd>
              </div>
            ))}
        </dl>
        <button className="btn-primary mt-4 w-full" onClick={onGenerate} disabled={busy}>
          {busy ? <Loader2 size={16} className="animate-spin" /> : <FileDown size={16} />}
          Generate Report PDF
        </button>
      </div>
      </div>
    </div>
  )
}

function Field({ label, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      <span className="label">{label}</span>
      {children}
    </label>
  )
}
