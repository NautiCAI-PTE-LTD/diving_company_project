import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Building2, ChevronDown, Plus, Search, X, Pencil, Mail, Phone, MapPin, User,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import { listClients, createClient } from '../lib/api'

/* -----------------------------------------------------------------------
 * <ClientPicker> — used in New Inspection Step 1.
 * Replaces the inline 5-field form with a searchable dropdown of clients
 * the company has already entered (stored once in the Clients directory).
 *
 * The surveyor only has to:
 *   1. Pick an existing client, OR
 *   2. Click "+ Quick add" if it's a new one (creates and selects it).
 *
 * Props:
 *   value        — currently-selected client id ('' if none)
 *   onSelect(c)  — called with the selected client object (or null to clear)
 * --------------------------------------------------------------------- */
export default function ClientPicker({ value, onSelect }) {
  const [open, setOpen]     = useState(false)
  const [rows, setRows]     = useState([])
  const [loading, setLoad]  = useState(false)
  const [q, setQ]           = useState('')
  const [adding, setAdding] = useState(false)
  const rootRef     = useRef(null)
  const triggerRef  = useRef(null)
  const dropdownRef = useRef(null)
  // Dropdown is portaled to <body> so it escapes every ancestor stacking
  // context (every `.glass` section creates one via `backdrop-filter`,
  // which made the inline dropdown get painted under the next section).
  // We measure the trigger and position the panel with `position: fixed`.
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 })

  useEffect(() => {
    setLoad(true)
    listClients().then(setRows).catch(() => {}).finally(() => setLoad(false))
  }, [])

  // Outside click — must consider both the inline trigger area and the
  // portaled dropdown, otherwise clicking the search field would close it.
  useEffect(() => {
    if (!open) return
    const onClick = (e) => {
      const inRoot = rootRef.current?.contains(e.target)
      const inDrop = dropdownRef.current?.contains(e.target)
      if (!inRoot && !inDrop) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  // Keep the portaled dropdown glued to the trigger across scroll/resize.
  useEffect(() => {
    if (!open) return
    const measure = () => {
      const el = triggerRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      setPos({ top: r.bottom + 8, left: r.left, width: r.width })
    }
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open])

  const selected = useMemo(
    () => rows.find((r) => r.id === value) || null,
    [rows, value],
  )

  const filtered = useMemo(() => {
    if (!q) return rows
    const ql = q.toLowerCase()
    return rows.filter((r) =>
      r.name?.toLowerCase().includes(ql) ||
      r.contact_person?.toLowerCase().includes(ql) ||
      r.contact_email?.toLowerCase().includes(ql))
  }, [rows, q])

  async function onQuickAdd(payload) {
    try {
      const c = await createClient(payload)
      setRows((rs) => [...rs, c].sort((a, b) => a.name.localeCompare(b.name)))
      onSelect(c)
      setAdding(false)
      setOpen(false)
      toast.success('Client added to directory')
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Could not add client')
    }
  }

  return (
    <div ref={rootRef} className="relative">
      {/* trigger */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 rounded-xl bg-white/[0.03] ring-1 ring-white/10 hover:ring-brand-500/40 px-3 py-2.5 text-left transition">
        {selected ? (
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-white font-medium truncate">
              <Building2 size={14} className="text-brand-300 shrink-0" />
              {selected.name}
            </div>
            <div className="text-xs text-slate-400 truncate">
              {[selected.contact_person, selected.contact_email].filter(Boolean).join(' · ') || '—'}
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-slate-400">
            <Building2 size={14} className="text-brand-300" />
            <span className="text-sm">Select a client / vessel owner…</span>
          </div>
        )}
        <ChevronDown size={16} className="text-slate-400 shrink-0" />
      </button>

      {/* selected summary card */}
      {selected && (
        <div className="mt-2 rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-3 text-xs text-slate-300">
          <div className="grid sm:grid-cols-2 gap-2">
            {selected.contact_person && (
              <Row icon={User}   text={selected.contact_person} />
            )}
            {selected.contact_email && (
              <Row icon={Mail}   text={selected.contact_email} />
            )}
            {selected.contact_phone && (
              <Row icon={Phone}  text={selected.contact_phone} />
            )}
            {(selected.address || selected.country) && (
              <Row icon={MapPin} text={[selected.address, selected.country].filter(Boolean).join(', ')} />
            )}
          </div>
          <div className="mt-2 flex items-center gap-3 text-[11px]">
            <button type="button" onClick={() => onSelect(null)}
                    className="text-rose-300 hover:text-rose-200 inline-flex items-center gap-1">
              <X size={11} /> Clear selection
            </button>
            <Link to="/clients" className="text-brand-300 hover:text-brand-200 inline-flex items-center gap-1">
              <Pencil size={11} /> Edit in Clients directory
            </Link>
          </div>
        </div>
      )}

      {/* dropdown — portaled to <body> so it can't be clipped by a sibling
         `.glass` section's stacking context. */}
      {open && createPortal(
        <div
          ref={dropdownRef}
          style={{ position: 'fixed', top: pos.top, left: pos.left, width: pos.width, zIndex: 60 }}
          className="rounded-xl bg-ink-900 ring-1 ring-white/10 shadow-2xl overflow-hidden">
          <div className="p-2 border-b border-white/5 flex items-center gap-2">
            <Search size={14} className="text-slate-400 ml-1" />
            <input
              autoFocus
              className="flex-1 bg-transparent outline-none text-sm text-white placeholder:text-slate-500 py-1"
              placeholder="Search clients…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="btn-outline !py-1 !px-2 text-xs">
              <Plus size={11} /> Quick add
            </button>
          </div>

          <div className="max-h-72 overflow-y-auto">
            {loading ? (
              <div className="p-4 text-center text-xs text-slate-400">Loading…</div>
            ) : filtered.length === 0 ? (
              <div className="p-6 text-center text-xs text-slate-400">
                {q ? <>No clients match "<span className="text-white">{q}</span>"</>
                   : <>No clients yet — use <span className="text-brand-300">Quick add</span> or visit the Clients page.</>}
              </div>
            ) : (
              filtered.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => { onSelect(c); setOpen(false); setQ('') }}
                  className="w-full text-left px-3 py-2 hover:bg-white/[0.04] border-b border-white/5 last:border-b-0">
                  <div className="flex items-center gap-2 text-white text-sm font-medium">
                    <Building2 size={12} className="text-brand-300" />
                    {c.name}
                  </div>
                  <div className="text-[11px] text-slate-400 truncate">
                    {[c.contact_person, c.contact_email, c.country].filter(Boolean).join(' · ')}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>,
        document.body,
      )}

      {adding && (
        <QuickAddModal initial={{ name: q }}
                       onCancel={() => setAdding(false)}
                       onSave={onQuickAdd} />
      )}
    </div>
  )
}

function Row({ icon: Icon, text }) {
  return (
    <div className="flex items-start gap-1.5">
      <Icon size={11} className="text-brand-300 mt-0.5 shrink-0" />
      <span className="truncate">{text}</span>
    </div>
  )
}

function QuickAddModal({ initial, onCancel, onSave }) {
  const [f, setF] = useState({
    name: '', address: '', contact_person: '',
    contact_email: '', contact_phone: '', country: '', notes: '',
    ...initial,
  })
  const set = (k) => (e) => setF((v) => ({ ...v, [k]: e.target.value }))
  function submit(e) {
    e.preventDefault()
    if (!f.name?.trim()) return
    onSave({ ...f, name: f.name.trim() })
  }

  // Portal to document.body so the overlay isn't trapped inside an ancestor
  // with `backdrop-filter` (the surrounding `.glass` section creates a new
  // containing block for `position: fixed`, which would otherwise clip the
  // modal to that section and let the rest of the page bleed through).
  return createPortal(
    <div className="fixed inset-0 z-[100] bg-ink-950/70 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
      <form onSubmit={submit}
            className="glass rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto my-auto">
        <div className="flex items-center justify-between p-4 border-b border-white/5">
          <h3 className="font-display text-white">Quick-add Client</h3>
          <button type="button" onClick={onCancel} className="text-slate-400 hover:text-white">
            <X size={16} />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <label className="block">
            <span className="label">Company / Vessel Owner Name *</span>
            <input className="input" autoFocus value={f.name} onChange={set('name')}
                   placeholder="WEST SQUADRON MARINE SERVICES" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="label">Contact Person</span>
              <input className="input" value={f.contact_person} onChange={set('contact_person')} />
            </label>
            <label className="block">
              <span className="label">Country</span>
              <input className="input" value={f.country} onChange={set('country')} />
            </label>
            <label className="block">
              <span className="label">Email</span>
              <input className="input" value={f.contact_email} onChange={set('contact_email')} />
            </label>
            <label className="block">
              <span className="label">Phone</span>
              <input className="input" value={f.contact_phone} onChange={set('contact_phone')} />
            </label>
          </div>
          <label className="block">
            <span className="label">Address</span>
            <textarea className="input" rows={2} value={f.address} onChange={set('address')} />
          </label>
        </div>
        <div className="flex items-center justify-end gap-2 p-3 border-t border-white/5">
          <button type="button" onClick={onCancel} className="btn-ghost">Cancel</button>
          <button type="submit" className="btn-primary">
            <Plus size={12} /> Add &amp; Select
          </button>
        </div>
      </form>
    </div>,
    document.body,
  )
}
