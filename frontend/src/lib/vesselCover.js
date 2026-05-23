/** Cover vs hull — models decide grids; OCR links the Photographic Report photo. */

/** Minimum confidence to auto-apply from batch OCR (not manual "Use for report"). */
export const MIN_AUTO_OCR_CONFIDENCE = 0.42

/** Short/noisy tokens often mis-read on hull paint (not the painted vessel name). */
const WEAK_GUESSES = new Set([
  'TUG', 'TUGS', 'MV', 'MS', 'MT', 'NA', 'NB', 'IT', 'OR', 'VS',
  'FPSO', 'OSV', 'AHTS', 'LNG', 'LPG', 'RTV',
])

/** Port of registry / city lines on the hull — not the vessel name. */
const REGISTRY_MARKS = new Set([
  'MONROVIA', 'LIBERIA', 'PANAMA', 'MALTA', 'HAMILTON', 'NASSAU', 'BAHAMAS',
  'SINGAPORE', 'HONGKONG', 'CYPRUS', 'MARSHALL', 'ISLE', 'MAN', 'MAJURO',
])

export function isCoverOnlyResult(result) {
  if (!result) return false
  return Boolean(
    result.cover_only
    || result.stage?.id === 'not_hull'
    || result.species?.top === 'vessel_cover',
  )
}

export function normalizeVesselName(name) {
  return String(name || '').toUpperCase().replace(/[^A-Z0-9]+/g, '')
}

export function vesselNamesMatch(a, b) {
  const na = normalizeVesselName(a)
  const nb = normalizeVesselName(b)
  if (!na || !nb) return false
  return na === nb || na.includes(nb) || nb.includes(na)
}

/**
 * Rank OCR rows — highest confidence wins, but short noise (e.g. "TUG" @ 99%)
 * loses to a real nameplate (e.g. "WOLVERINE" @ 87%).
 */
export function ocrCandidateScore(guess, confidence) {
  const g = normalizeVesselName(guess)
  const conf = Number(confidence) || 0
  if (!g || conf <= 0) return 0

  let score = conf
  const len = g.length

  if (WEAK_GUESSES.has(g) || REGISTRY_MARKS.has(g)) score *= 0.12
  else if (len <= 3) score *= 0.2
  else if (len === 4 && conf < 0.92) score *= 0.45
  else if (len < 6 && conf < 0.75) score *= 0.55
  else if (len >= 6) score *= 1.05

  return Math.min(score, 1.0)
}

/** One analyse/OCR API payload → rows for each candidate (same image_id). */
export function expandOcrResultRows(result) {
  if (!result) return []
  const vo = result.vessel_ocr || result
  const imageId = result.image_id || vo?.image_id || ''
  const cands = vo?.candidates
  if (Array.isArray(cands) && cands.length) {
    return cands
      .map((c) => ({
        vessel_ocr: {
          best_guess: (c.text || c.best_guess || '').trim(),
          best_confidence: Number(c.confidence ?? c.best_confidence ?? 0),
        },
        image_id: imageId,
      }))
      .filter((row) => row.vessel_ocr.best_guess)
  }
  const guess = (vo?.best_guess || result?.best_guess || '').trim()
  if (!guess) return []
  return [{
    vessel_ocr: {
      best_guess: guess,
      best_confidence: Number(vo?.best_confidence ?? vo?.confidence ?? 0),
    },
    image_id: imageId,
  }]
}

export function rowToOcrPick(row) {
  const vo = row?.vessel_ocr || row
  const guess = (vo?.best_guess || row?.best_guess || '').trim()
  const conf = Number(vo?.best_confidence ?? vo?.confidence ?? row?.confidence ?? 0)
  const imageId = row?.image_id || vo?.image_id || ''
  return {
    guess,
    confidence: conf,
    imageId,
    score: ocrCandidateScore(guess, conf),
  }
}

function shareNameplateSuffix(a, b, minLen = 5) {
  const na = normalizeVesselName(a)
  const nb = normalizeVesselName(b)
  if (!na || !nb || na === nb) return na === nb
  const n = Math.min(minLen, na.length, nb.length)
  return na.slice(-n) === nb.slice(-n)
}

/** Prefer full nameplate (e.g. SILVERSTONE) over a shorter mis-read (e.g. VERSTONE). */
export function resolveNameConflicts(picks) {
  if (!picks.length) return null
  const sorted = [...picks].filter(
    (p) => p.guess && !REGISTRY_MARKS.has(normalizeVesselName(p.guess)),
  ).sort((a, b) => b.score - a.score)
  if (!sorted.length) return picks[0]

  const topScore = sorted[0].score
  const tier = sorted.filter((p) => p.score >= topScore * 0.82)
  tier.sort((a, b) => {
    const lenDiff = b.guess.length - a.guess.length
    if (lenDiff !== 0) return lenDiff
    return b.score - a.score
  })
  let best = tier[0]

  for (const pick of sorted) {
    const pg = normalizeVesselName(pick.guess)
    const bg = normalizeVesselName(best.guess)
    if (pg.length > bg.length && bg.length >= 4 && (pg.includes(bg) || shareNameplateSuffix(pick.guess, best.guess))
        && pick.confidence >= 0.55 && pick.score >= best.score * 0.65) {
      best = pick
    }
  }
  return best
}

/** Best OCR for one analyse/API payload (never mixes other uploads). */
export function pickOcrFromAnalyzeResult(result) {
  const imageId = result?.image_id || result?.vessel_ocr?.image_id || ''
  const rows = expandOcrResultRows(result)
  if (!rows.length) return null
  const pick = pickBestVesselOcr(rows, {})
  return pick?.guess ? { ...pick, imageId: imageId || pick.imageId } : null
}

/**
 * Pick the best OCR row by quality score (not upload order).
 * Name and image_id always come from the same row.
 */
export function pickBestVesselOcr(candidates, current = null) {
  const picks = []
  for (const row of candidates) {
    const pick = rowToOcrPick(row)
    if (pick.guess) picks.push(pick)
  }
  if (current?.guess) {
    picks.push({
      guess: current.guess,
      confidence: Number(current.confidence) || 0,
      imageId: current.imageId || '',
      score: Number(current.score) || ocrCandidateScore(current.guess, current.confidence),
    })
  }
  if (!picks.length) {
    return { guess: '', confidence: 0, imageId: '', score: 0 }
  }
  return resolveNameConflicts(picks) || picks[0]
}

/** Best OCR for a specific persisted cover image (keeps name aligned with photo). */
export function pickOcrForImageId(candidates, imageId) {
  if (!imageId) return null
  const rows = candidates.filter((row) => {
    const id = row?.image_id || row?.vessel_ocr?.image_id || ''
    return id === imageId
  })
  if (!rows.length) return null
  return pickBestVesselOcr(rows, {})
}

export function shouldAutoApplyOcr(best) {
  if (!best?.guess) return false
  if (best.confidence < MIN_AUTO_OCR_CONFIDENCE) return false
  if (best.score < MIN_AUTO_OCR_CONFIDENCE * 0.85) return false
  const g = normalizeVesselName(best.guess)
  if (WEAK_GUESSES.has(g) && best.confidence < 0.95) return false
  return g.length >= 4 || best.confidence >= 0.88
}

/**
 * Apply OCR pick to wizard state.
 * @param {object} opts.force — manual "Use for report" always overwrites name + cover
 */
/** Local blob preview from analysed hull grids (before auth fetch completes). */
export function findLocalImageUrl(imagesByRegion, imageId) {
  if (!imageId) return ''
  for (const arr of Object.values(imagesByRegion || {})) {
    for (const item of arr || []) {
      if (item?.backendId === imageId && item?.url) return item.url
    }
  }
  return ''
}

/** One OCR result per uploaded nameplate image (for cycling cover photos). */
export function buildCoverAlternatesFromOcrRows(rows) {
  const byId = new Map()
  for (const row of rows || []) {
    const pick = rowToOcrPick(row)
    if (!pick.imageId || !pick.guess) continue
    const prev = byId.get(pick.imageId)
    if (!prev || pick.score > prev.score) byId.set(pick.imageId, pick)
  }
  return [...byId.values()].sort((a, b) => b.score - a.score)
}

function altToPick(a) {
  return {
    imageId: a.imageId || a.image_id || '',
    guess: a.guess || a.display_name || '',
    confidence: Number(a.confidence) || 0,
    score: Number(a.score) || ocrCandidateScore(a.guess || a.display_name, a.confidence),
    likelyTruncated: Boolean(a.likely_truncated || a.likelyTruncated),
    matchesBestName: Boolean(a.matches_best_name ?? a.matchesBestName),
  }
}

export function mapCoverAlternatesFromApi(alternates) {
  return (alternates || []).map(altToPick).filter((a) => a.imageId && a.guess)
}

/** Best name + photo across all nameplate angles (OCR compares every reading). */
export function pickBestCoverAlternate(alternates) {
  const picks = (alternates || []).map(altToPick).filter((p) => p.guess)
  if (!picks.length) return null
  return resolveNameConflicts(picks)
}

/**
 * Next nameplate angle with a better OCR vessel name than the current cover.
 * Skips truncated mis-reads (VERSTONE) when a longer match exists (SILVERSTONE).
 */
export function pickNextBetterCoverAlternate(alternates, currentImageId, currentGuess) {
  const picks = (alternates || []).map(altToPick).filter((p) => p.guess)
  if (!picks.length) return null
  if (picks.length === 1) return null

  const ranked = [...picks].sort((a, b) => {
    if (a.likelyTruncated !== b.likelyTruncated) return a.likelyTruncated ? 1 : -1
    if (a.matchesBestName !== b.matchesBestName) return a.matchesBestName ? -1 : 1
    const lenDiff = b.guess.length - a.guess.length
    if (lenDiff !== 0 && Math.abs(a.score - b.score) < 0.12) return lenDiff
    return b.score - a.score
  })

  const curId = (currentImageId || '').trim()
  const curNorm = normalizeVesselName(currentGuess)
  const curIdx = ranked.findIndex((p) => p.imageId === curId)
  const curPick = curIdx >= 0 ? ranked[curIdx] : null

  const globalBest = resolveNameConflicts(picks)
  if (globalBest && globalBest.imageId !== curId) {
    const bn = normalizeVesselName(globalBest.guess)
    const longer = bn.length > curNorm.length && (
      bn.includes(curNorm) || shareNameplateSuffix(globalBest.guess, currentGuess)
    )
    const betterScore = globalBest.score > (curPick?.score ?? 0) * 1.03
    if (longer || betterScore) return globalBest
  }

  for (let step = 1; step < ranked.length; step++) {
    const idx = curIdx < 0 ? step - 1 : (curIdx + step) % ranked.length
    const cand = ranked[idx]
    if (!cand || cand.imageId === curId) continue
    const cn = normalizeVesselName(cand.guess)
    if (cand.likelyTruncated && !curPick?.likelyTruncated) continue
    if (cn.length > curNorm.length && shareNameplateSuffix(cand.guess, currentGuess)) {
      return cand
    }
    if (cn !== curNorm && cand.score >= (curPick?.score ?? 0) * 0.9) {
      return cand
    }
  }

  const nextIdx = curIdx < 0 ? 0 : (curIdx + 1) % ranked.length
  const fallback = ranked[nextIdx]
  return fallback?.imageId !== curId ? fallback : ranked[(nextIdx + 1) % ranked.length]
}

export function applyVesselOcrToReport(store, best, { silent = false, toast, force = false } = {}) {
  if (!best?.guess) return false

  const prevName = (store.vessel.vesselName || '').trim()
  const prevScore = ocrCandidateScore(prevName, store.vesselOcrConfidence || 0)

  const shouldApply = force || !prevName || best.score >= prevScore
  if (!shouldApply) return false

  store.updateVessel({ vesselName: best.guess })
  if (best.imageId) {
    store.setVesselImageId(best.imageId)
  }
  if (typeof store.setVesselOcrMeta === 'function') {
    store.setVesselOcrMeta({
      guess: best.guess,
      imageId: best.imageId || '',
      confidence: best.confidence,
      score: best.score,
    })
  }

  if (!silent && toast) {
    toast.success(
      best.imageId
        ? `${best.guess} (${(best.confidence * 100).toFixed(0)}%) — name & Photographic cover updated`
        : `Vessel name: ${best.guess} (${(best.confidence * 100).toFixed(0)}%)`,
    )
  }
  return true
}
