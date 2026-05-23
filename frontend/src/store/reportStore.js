import { create } from 'zustand'
import { autoDetectVessel, fetchCoverAlternates, fetchImageVesselOcr, friendlyApiDetail } from '../lib/api'
import {
  applyVesselOcrToReport,
  buildCoverAlternatesFromOcrRows,
  expandOcrResultRows,
  mapCoverAlternatesFromApi,
  pickBestVesselOcr,
  pickNextBetterCoverAlternate,
  pickOcrForImageId,
  pickOcrFromAnalyzeResult,
  rowToOcrPick,
  shouldAutoApplyOcr,
  vesselNamesMatch,
} from '../lib/vesselCover'

const emptyDay = () => ({
  date: '',
  time_left_base: '', time_arrived_jobsite: '',
  dive_ops_started: '', dive_ops_completed: '',
  time_left_jobsite: '', time_arrived_base: '',
  standby_from: '', standby_to: '', remarks: '',
})

const emptyCrew = (label = 'Diving Team - 1') => ({
  label,
  supervisor: '', divers: '', boat_captain: '',
  sea: { weather: 'Sunny', sea: 'Choppy', visibility: '', tide: '' },
  days: [emptyDay()],
  remarks: '',
})

const initialVessel = {
  vesselName: '',
  vesselType: 'Cargo',
  vesselClass: 'BV',
  jobNo: '',
  jobScope: 'Under-Hull Cleaning & Propeller Polishing',
  loa: '',
  draft: '',
  location: '',
  diveDate: '',
  weather: 'Sunny',
  sea: 'Choppy',
  visibility: '',
  tide: '',
  captain: '',
  diveSupervisor: '',
  divers: '',             // kept for back-compat; UI now uses `team` array
  boatCaptain: '',
  notes: '',
  // Client (vessel owner) — this is the company that owns/operates the vessel.
  // It is printed at the top of every report page and is the *priority* brand.
  client: {
    company: '',
    address: '',
    contact_person: '',
    contact_email: '',
    contact_phone: '',
  },
  // Client-side reps (Captain etc.) shown under CLIENT REPRESENTATIVES.
  client_reps: [],   // [{ role: 'Captain', name: 'Lyndon Llanos' }]
  // Legacy flat team list — still kept for back-compat but the wizard
  // now drives multi-crew operations via `crews` below.
  team: [],
  // NEW: one or more dive crews. Each has its own supervisor, divers,
  // boat captain, sea conditions, and per-day timings.
  crews: [emptyCrew('Diving Team - 1')],
  extra: {},
}

// Default per-region inspection record
export const emptyFindings = () => ({
  inspection_done: true,
  overall_condition: 'Good',
  damage_observed: false,
  damage_notes: '',
  notes: '',
})

export const useReport = create((set, get) => ({
  step: 0,
  vessel: { ...initialVessel },
  // images is keyed by region id; each entry is an array of image objects:
  // { id, file, url, name, size, status: 'pending'|'analyzing'|'done'|'error', result }
  images: {},
  regionInspections: {},  // { regionId: RegionFindings }
  vesselImageId: '',      // image_id returned by /api/ocr/vessel?persist=true
  vesselOcrConfidence: 0, // best auto/manual OCR confidence (0–1)
  vesselOcrScore: 0,      // quality score used to pick name over noise like "TUG"
  ocrCandidateRows: [],   // analyse/OCR rows — kept for Vessel step + PDF
  coverAlternates: [],    // [{ imageId, guess, confidence, score }] nameplate photos
  clientId: '',           // id from the Clients directory (one-time entry)

  setStep: (step) => set({ step }),
  next: () => {
    const step = Math.min(get().step + 1, 3)
    set({ step })
    if (step === 1) {
      get().ensureVesselCover(true)
    }
  },
  prev: () => set({ step: Math.max(get().step - 1, 0) }),

  updateVessel: (patch) => set({ vessel: { ...get().vessel, ...patch } }),
  updateClient: (patch) => set({
    vessel: { ...get().vessel, client: { ...(get().vessel.client || {}), ...patch } },
  }),
  setVesselImageId: (id) => set({ vesselImageId: id || '' }),
  setVesselOcrMeta: ({ guess, imageId, confidence, score }) => set({
    vesselOcrConfidence: Number(confidence) || 0,
    vesselOcrScore: Number(score) || 0,
    ...(guess ? { vessel: { ...get().vessel, vesselName: guess } } : {}),
    ...(imageId ? { vesselImageId: imageId } : {}),
  }),

  /** Track OCR from analyse + batch sweep; survives leaving Upload step. */
  pushOcrCandidate: (row) => {
    const expanded = expandOcrResultRows(row)
    const incoming = expanded.length ? expanded : (row?.vessel_ocr?.best_guess || row?.best_guess ? [row] : [])
    if (!incoming.length) return
    const replaceIds = new Set(
      incoming.map((r) => r?.image_id || r?.vessel_ocr?.image_id).filter(Boolean),
    )
    const kept = get().ocrCandidateRows.filter((r) => {
      const id = r?.image_id || r?.vessel_ocr?.image_id || ''
      return !id || !replaceIds.has(id)
    })
    const rows = [...kept, ...incoming]
    set({ ocrCandidateRows: rows })
    const coverId = get().vesselImageId
    const best = coverId
      ? pickOcrForImageId(rows, coverId)
      : pickBestVesselOcr(rows, {
        guess: get().vessel.vesselName,
        imageId: coverId,
        confidence: get().vesselOcrConfidence,
        score: get().vesselOcrScore,
      })
    if (shouldAutoApplyOcr(best)) {
      applyVesselOcrToReport(get(), best, { silent: true })
    }
  },

  /** Collect backend image ids from OCR rows + analysed hull grids. */
  collectUploadImageIds: () => {
    const ids = new Set()
    for (const row of get().ocrCandidateRows) {
      const id = row?.image_id || row?.vessel_ocr?.image_id || ''
      if (id) ids.add(id)
    }
    for (const arr of Object.values(get().images)) {
      for (const item of arr || []) {
        if (item?.backendId) ids.add(item.backendId)
      }
    }
    return [...ids]
  },

  /**
   * Fully automated vessel name + cover from all uploaded/analysed images.
   * No manual vessel list required — models + OCR on nameplate photos.
   */
  autoDetectVesselFromUpload: async ({ toast } = {}) => {
    const ids = get().collectUploadImageIds()
    if (!ids.length) return false
    const pinned = (get().vessel.vesselName || '').trim()
    try {
      const data = await autoDetectVessel(ids, { pinnedVesselName: pinned })
      if (!data?.display_name) return false
      const pick = {
        guess: data.display_name,
        imageId: data.cover_image_id || get().vesselImageId || '',
        confidence: Number(data.confidence) || 0,
        score: Number(data.score) || 0,
      }
      if (data.cover_image_id) {
        get().pushOcrCandidate({
          image_id: data.cover_image_id,
          vessel_ocr: {
            best_guess: data.display_name,
            best_confidence: data.confidence,
            image_id: data.cover_image_id,
          },
        })
      }
      let alts = mapCoverAlternatesFromApi(data.cover_alternates)
      if (!alts.length) alts = buildCoverAlternatesFromOcrRows(get().ocrCandidateRows)
      if (alts.length) set({ coverAlternates: alts })
      const ok = applyVesselOcrToReport(get(), pick, { silent: !toast, toast, force: true })
      if (toast && data.needs_review && data.review_reason) {
        toast(data.review_reason, { icon: '⚠️', duration: 6000 })
      }
      return ok
    } catch (err) {
      console.warn('autoDetectVesselFromUpload failed', err)
      return false
    }
  },

  /** Load / refresh ranked nameplate list from the server. */
  refreshCoverAlternates: async ({ refreshOcr = true } = {}) => {
    const ids = get().collectUploadImageIds()
    if (!ids.length) {
      const local = buildCoverAlternatesFromOcrRows(get().ocrCandidateRows)
      if (local.length) set({ coverAlternates: local })
      return local
    }
    try {
      const data = await fetchCoverAlternates(ids, { refreshOcr })
      const alts = mapCoverAlternatesFromApi(data.cover_alternates)
      if (alts.length) set({ coverAlternates: alts })
      return alts
    } catch (err) {
      console.warn('refreshCoverAlternates failed', err)
      return buildCoverAlternatesFromOcrRows(get().ocrCandidateRows)
    }
  },

  /** Use a specific nameplate photo + OCR text as the report cover (client picks angle). */
  applyCoverAlternate: async (imageId, { toast } = {}) => {
    const id = (imageId || '').trim()
    if (!id) return false
    await get().syncVesselOcrFromServer(id, { refresh: true })
    const fromServer = pickOcrForImageId(get().ocrCandidateRows, id)
    const alts = get().coverAlternates
    const alt = alts.find((a) => a.imageId === id)
    const pick = fromServer?.guess
      ? { ...fromServer, imageId: id }
      : alt
        ? { ...alt, imageId: id }
        : null
    if (!pick?.guess) {
      if (toast) toast.error('No vessel name read on that photo')
      return false
    }
    get().pushOcrCandidate({
      image_id: id,
      vessel_ocr: {
        best_guess: pick.guess,
        best_confidence: pick.confidence,
        image_id: id,
      },
    })
    applyVesselOcrToReport(get(), pick, { silent: true, force: true })
    if (toast) {
      toast.success(`${pick.guess} (${(pick.confidence * 100).toFixed(0)}% OCR) — cover updated`)
    }
    return true
  },

  /**
   * Try another nameplate angle: re-OCR that photo and pick a better vessel name
   * (e.g. SILVERSTONE instead of VERSTONE on a different bow photo).
   */
  cycleToNextCoverAlternate: async ({ toast } = {}) => {
    const prevName = (get().vessel.vesselName || '').trim()
    const prevId = get().vesselImageId?.trim()

    let alts = await get().refreshCoverAlternates({ refreshOcr: true })
    if (!alts.length) {
      alts = buildCoverAlternatesFromOcrRows(get().ocrCandidateRows)
      if (alts.length) set({ coverAlternates: alts })
    }
    if (alts.length < 2) {
      if (toast) {
        toast('Only one nameplate-style photo found — upload another angle of the ship name.', { icon: 'ℹ️' })
      }
      return false
    }

    const next = pickNextBetterCoverAlternate(alts, prevId, prevName)
    if (!next?.imageId) {
      if (toast) toast('No better nameplate reading found in this batch.', { icon: 'ℹ️' })
      return false
    }

    await get().syncVesselOcrFromServer(next.imageId, { refresh: true })
    const fromServer = pickOcrForImageId(get().ocrCandidateRows, next.imageId)
    const pick = fromServer?.guess
      ? { ...fromServer, imageId: next.imageId }
      : { ...next, imageId: next.imageId }

    get().pushOcrCandidate({
      image_id: pick.imageId,
      vessel_ocr: {
        best_guess: pick.guess,
        best_confidence: pick.confidence,
        image_id: pick.imageId,
      },
    })
    applyVesselOcrToReport(get(), pick, { silent: true, force: true })

    const refreshed = await get().refreshCoverAlternates({ refreshOcr: false })
    const idx = (refreshed.length ? refreshed : alts).findIndex((a) => a.imageId === pick.imageId) + 1
    const total = (refreshed.length ? refreshed : alts).length

    if (toast) {
      const msg = prevName && prevName !== pick.guess
        ? `OCR on new angle: ${prevName} → ${pick.guess} (${(pick.confidence * 100).toFixed(0)}%)`
        : `${pick.guess} (${(pick.confidence * 100).toFixed(0)}% OCR) from nameplate ${idx}/${total}`
      toast.success(msg)
    }
    return true
  },

  /** Re-OCR the cover image on the server (survives page refresh). */
  syncVesselOcrFromServer: async (imageId, { refresh = true, toast } = {}) => {
    const id = (imageId || get().vesselImageId || '').trim()
    if (!id) return false
    try {
      const data = await fetchImageVesselOcr(id, { refresh })
      get().pushOcrCandidate({
        image_id: data.image_id || id,
        vessel_ocr: data.vessel_ocr || data,
      })
      const pick = pickOcrForImageId(get().ocrCandidateRows, id)
        || pickOcrFromAnalyzeResult({ image_id: id, vessel_ocr: data.vessel_ocr || data })
        || rowToOcrPick({
          image_id: id,
          vessel_ocr: data.vessel_ocr || {
            best_guess: data.best_guess,
            best_confidence: data.best_confidence,
          },
        })
      if (!pick?.guess) return false
      return applyVesselOcrToReport(get(), pick, { silent: !toast, toast, force: true })
    } catch (err) {
      console.warn('syncVesselOcrFromServer failed', err)
      if (toast) {
        const raw = err?.response?.data?.detail || err?.message || ''
        toast.error(
          friendlyApiDetail(raw, 'Could not re-read vessel name from cover photo'),
        )
      }
      return false
    }
  },

  applyCoverFromAnalyze: (result) => {
    const pick = pickOcrFromAnalyzeResult(result)
    if (!pick?.guess) return false
    get().pushOcrCandidate(result)
    return applyVesselOcrToReport(get(), pick, { silent: true, force: true })
  },

  /** Apply best OCR to name + cover (e.g. when opening Vessel step). */
  ensureVesselCover: (force = true) => {
    const rows = get().ocrCandidateRows
    const imageId = get().vesselImageId
    if (imageId) {
      const forPhoto = pickOcrForImageId(rows, imageId)
      if (forPhoto?.guess) {
        const cur = (get().vessel.vesselName || '').trim()
        if (force || !cur || !vesselNamesMatch(cur, forPhoto.guess)) {
          return applyVesselOcrToReport(get(), forPhoto, { silent: true, force: true })
        }
      }
    }
    if (!rows.length) return false
    const best = pickBestVesselOcr(rows, {
      guess: get().vessel.vesselName,
      imageId: get().vesselImageId,
      confidence: get().vesselOcrConfidence,
      score: get().vesselOcrScore,
    })
    if (!best?.guess) return false
    return applyVesselOcrToReport(get(), best, { silent: true, force })
  },

  // Selecting a client from the directory: stash both the id (for /api/reports)
  // and a copy of its details on `vessel.client` so the wizard summary + PDF
  // render correctly even before the report is saved.
  setClientFromDirectory: (c) => {
    if (!c) {
      set({
        clientId: '',
        vessel: {
          ...get().vessel,
          client: { company: '', address: '', contact_person: '',
                     contact_email: '', contact_phone: '' },
        },
      })
      return
    }
    set({
      clientId: c.id,
      vessel: {
        ...get().vessel,
        client: {
          company:        c.name           || '',
          address:        c.address        || '',
          contact_person: c.contact_person || '',
          contact_email:  c.contact_email  || '',
          contact_phone:  c.contact_phone  || '',
        },
      },
    })
  },

  addTeamMember: (member = { role: 'Diver', name: '' }) => {
    const t = [...(get().vessel.team || []), { ...member }]
    set({ vessel: { ...get().vessel, team: t } })
  },
  updateTeamMember: (idx, patch) => {
    const t = [...(get().vessel.team || [])]
    if (!t[idx]) return
    t[idx] = { ...t[idx], ...patch }
    set({ vessel: { ...get().vessel, team: t } })
  },
  removeTeamMember: (idx) => {
    const t = (get().vessel.team || []).filter((_, i) => i !== idx)
    set({ vessel: { ...get().vessel, team: t } })
  },

  // ---------- Client representatives -----------------------------
  addClientRep: (rep = { role: 'Captain', name: '' }) => {
    const reps = [...(get().vessel.client_reps || []), { ...rep }]
    set({ vessel: { ...get().vessel, client_reps: reps } })
  },
  updateClientRep: (idx, patch) => {
    const reps = [...(get().vessel.client_reps || [])]
    if (!reps[idx]) return
    reps[idx] = { ...reps[idx], ...patch }
    set({ vessel: { ...get().vessel, client_reps: reps } })
  },
  removeClientRep: (idx) => {
    const reps = (get().vessel.client_reps || []).filter((_, i) => i !== idx)
    set({ vessel: { ...get().vessel, client_reps: reps } })
  },

  // ---------- Crews ----------------------------------------------
  addCrew: () => {
    const crews = [...(get().vessel.crews || [])]
    crews.push(emptyCrew(`Diving Team - ${crews.length + 1}`))
    set({ vessel: { ...get().vessel, crews } })
  },
  updateCrew: (idx, patch) => {
    const crews = [...(get().vessel.crews || [])]
    if (!crews[idx]) return
    crews[idx] = { ...crews[idx], ...patch }
    set({ vessel: { ...get().vessel, crews } })
  },
  updateCrewSea: (idx, patch) => {
    const crews = [...(get().vessel.crews || [])]
    if (!crews[idx]) return
    crews[idx] = { ...crews[idx], sea: { ...(crews[idx].sea || {}), ...patch } }
    set({ vessel: { ...get().vessel, crews } })
  },
  removeCrew: (idx) => {
    const crews = (get().vessel.crews || []).filter((_, i) => i !== idx)
    // ensure at least one crew always exists
    if (crews.length === 0) crews.push(emptyCrew('Diving Team - 1'))
    set({ vessel: { ...get().vessel, crews } })
  },
  addCrewDay: (idx) => {
    const crews = [...(get().vessel.crews || [])]
    if (!crews[idx]) return
    const days = [...(crews[idx].days || []), emptyDay()]
    crews[idx] = { ...crews[idx], days }
    set({ vessel: { ...get().vessel, crews } })
  },
  updateCrewDay: (idx, dayIdx, patch) => {
    const crews = [...(get().vessel.crews || [])]
    if (!crews[idx]) return
    const days = [...(crews[idx].days || [])]
    if (!days[dayIdx]) return
    days[dayIdx] = { ...days[dayIdx], ...patch }
    crews[idx] = { ...crews[idx], days }
    set({ vessel: { ...get().vessel, crews } })
  },
  removeCrewDay: (idx, dayIdx) => {
    const crews = [...(get().vessel.crews || [])]
    if (!crews[idx]) return
    const days = (crews[idx].days || []).filter((_, i) => i !== dayIdx)
    crews[idx] = { ...crews[idx], days }
    set({ vessel: { ...get().vessel, crews } })
  },

  updateFinding: (regionId, patch) => {
    const prev = get().regionInspections[regionId] || emptyFindings()
    set({
      regionInspections: {
        ...get().regionInspections,
        [regionId]: { ...prev, ...patch },
      },
    })
  },
  updateFindingSubblock: (regionId, blockKey, patch) => {
    const prev = get().regionInspections[regionId] || emptyFindings()
    const block = prev[blockKey] || {}
    set({
      regionInspections: {
        ...get().regionInspections,
        [regionId]: { ...prev, [blockKey]: { ...block, ...patch } },
      },
    })
  },

  addImages: (regionId, files) => {
    const incoming = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      url: URL.createObjectURL(file),
      name: file.name,
      size: file.size,
      status: 'pending',
      result: null,
    }))
    set({
      images: {
        ...get().images,
        [regionId]: [...(get().images[regionId] || []), ...incoming],
      },
    })
  },

  /** Append a pre-analyzed item (image OR video frame) to a region bucket.
   *  Used by auto-routing: the analyser already returned a region + result so
   *  there's no further work to do client-side. */
  addAnalyzedImage: (regionId, entry) => {
    if (regionId === 'vessel_cover' || entry?.result?.cover_only || entry?.result?.is_overview) {
      return
    }
    const item = {
      id: entry.id || crypto.randomUUID(),
      file: entry.file || null,
      url: entry.url,
      name: entry.name,
      size: entry.size || 0,
      status: 'done',
      result: entry.result,
      backendId: entry.backendId,
      kind: entry.kind || 'image',     // 'image' | 'frame'
      ts_sec: entry.ts_sec,
      source_filename: entry.source_filename,
    }
    set({
      images: {
        ...get().images,
        [regionId]: [...(get().images[regionId] || []), item],
      },
    })
  },

  /** Manually move an item to another region (override the AI's choice). */
  moveImage: (fromRegion, imageId, toRegion) => {
    if (fromRegion === toRegion) return
    const from = (get().images[fromRegion] || [])
    const idx = from.findIndex((i) => i.id === imageId)
    if (idx < 0) return
    const item = from[idx]
    set({
      images: {
        ...get().images,
        [fromRegion]: from.filter((i) => i.id !== imageId),
        [toRegion]:   [...(get().images[toRegion] || []), item],
      },
    })
  },

  updateImage: (regionId, imageId, patch) => {
    const list = (get().images[regionId] || []).map((img) =>
      img.id === imageId ? { ...img, ...patch } : img,
    )
    set({ images: { ...get().images, [regionId]: list } })
  },

  removeImage: (regionId, imageId) => {
    const list = (get().images[regionId] || []).filter((img) => {
      if (img.id === imageId) {
        if (img.file) {            // only revoke URLs we created from local Files
          try { URL.revokeObjectURL(img.url) } catch { /* noop */ }
        }
        return false
      }
      return true
    })
    set({ images: { ...get().images, [regionId]: list } })
  },

  totalImages: () =>
    Object.values(get().images).reduce((n, arr) => n + arr.length, 0),

  reset: () => {
    Object.values(get().images).forEach((arr) =>
      arr.forEach((img) => { try { URL.revokeObjectURL(img.url) } catch { /* noop */ } }),
    )
    set({
      step: 0,
      vessel: {
        ...initialVessel,
        client_reps: [],
        team: [],
        crews: [emptyCrew('Diving Team - 1')],
        extra: {},
      },
      images: {},
      regionInspections: {},
      vesselImageId: '',
      vesselOcrConfidence: 0,
      vesselOcrScore: 0,
      ocrCandidateRows: [],
      coverAlternates: [],
      clientId: '',
    })
  },
}))
