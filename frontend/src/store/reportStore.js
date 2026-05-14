import { create } from 'zustand'

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
  clientId: '',           // id from the Clients directory (one-time entry)

  setStep: (step) => set({ step }),
  next: () => set({ step: Math.min(get().step + 1, 3) }),
  prev: () => set({ step: Math.max(get().step - 1, 0) }),

  updateVessel: (patch) => set({ vessel: { ...get().vessel, ...patch } }),
  updateClient: (patch) => set({
    vessel: { ...get().vessel, client: { ...(get().vessel.client || {}), ...patch } },
  }),
  setVesselImageId: (id) => set({ vesselImageId: id || '' }),

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
      clientId: '',
    })
  },
}))
