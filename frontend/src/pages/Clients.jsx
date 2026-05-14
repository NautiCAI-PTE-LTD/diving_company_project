import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'framer-motion'
import {
  Users, Plus, Pencil, Trash2, Search, X, Save, Building2,
  Mail, Phone, MapPin, User, Globe,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  listClients, createClient, updateClient, deleteClient,
} from '../lib/api'

const EMPTY = {
  name: '', address: '', contact_person: '', contact_email: '',
  contact_phone: '', country: '', notes: '',
}

/* -----------------------------------------------------------------------
 * Clients directory page — vessel-owner details entered once per company
 * so the surveyor doesn't retype them on every inspection.
 * --------------------------------------------------------------------- */
export default function Clients() {
  const [rows, setRows]       = useState([])
  const [loading, setLoading] = useState(true)
  const [q, setQ]             = useState('')
  const [editing, setEditing] = useState(null)   // null | {…} | 'new'

  async function refresh(query = '') {
    setLoading(true)
    try {
      const data = await listClients({ q: query || undefined })
      setRows(data)
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to load clients')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  // Debounced search
  useEffect(() => {
    const t = setTimeout(() => refresh(q), 250)
    return () => clearTimeout(t)
  }, [q])

  async function onSave(payload, id) {
    try {
      if (id) {
        await updateClient(id, payload)
        toast.success('Client updated')
      } else {
        await createClient(payload)
        toast.success('Client added')
      }
      setEditing(null)
      refresh(q)
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Save failed')
    }
  }

  async function onDelete(row) {
    if (!confirm(`Delete client "${row.name}"? Past reports referencing it will keep a copy of the details.`)) return
    try {
      await deleteClient(row.id)
      toast.success('Deleted')
      refresh(q)
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Delete failed')
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-brand-300">Directory</div>
          <h1 className="font-display text-3xl font-bold text-white">Clients &amp; Vessel Owners</h1>
          <p className="text-sm text-slate-400 max-w-xl">
            Add each client once. They become pickable in the
            <span className="text-brand-300"> New Inspection </span>
            wizard, so contact, address and billing details never need to be retyped.
          </p>
        </div>
        <button onClick={() => setEditing('new')} className="btn-primary">
          <Plus size={14} /> Add Client
        </button>
      </header>

      {/* Search bar */}
      <div className="glass rounded-2xl p-3 flex items-center gap-2">
        <Search size={16} className="text-slate-400 ml-2" />
        <input
          className="bg-transparent outline-none flex-1 text-sm text-white placeholder:text-slate-500 py-1.5"
          placeholder="Search by company, contact, or email…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {q && (
          <button onClick={() => setQ('')} className="text-slate-400 hover:text-white">
            <X size={14} />
          </button>
        )}
      </div>

      {/* Table */}
      <div className="glass rounded-2xl overflow-hidden">
        {loading ? (
          <div className="p-10 text-center text-slate-400 text-sm">Loading…</div>
        ) : rows.length === 0 ? (
          <EmptyState onAdd={() => setEditing('new')} />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-white/[0.03] text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="text-left px-4 py-3">Client</th>
                <th className="text-left px-4 py-3">Contact</th>
                <th className="text-left px-4 py-3">Location</th>
                <th className="text-right px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-t border-white/5 hover:bg-white/[0.02]">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 text-white font-medium">
                      <Building2 size={14} className="text-brand-300" />
                      {c.name}
                    </div>
                    {c.notes && (
                      <div className="text-xs text-slate-400 mt-0.5 line-clamp-1">{c.notes}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-300">
                    <div>{c.contact_person || '—'}</div>
                    <div className="text-xs text-slate-400">
                      {c.contact_email || c.contact_phone || ''}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-300 text-xs">
                    {c.address ? <div className="line-clamp-2">{c.address}</div> : '—'}
                    {c.country && <div className="text-slate-400">{c.country}</div>}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setEditing(c)}
                      className="btn-ghost text-xs"
                      title="Edit"
                    >
                      <Pencil size={12} /> Edit
                    </button>
                    <button
                      onClick={() => onDelete(c)}
                      className="btn-ghost text-xs text-rose-300"
                      title="Delete"
                    >
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing !== null && (
        <ClientModal
          initial={editing === 'new' ? EMPTY : editing}
          onClose={() => setEditing(null)}
          onSave={(p) => onSave(p, editing === 'new' ? null : editing.id)}
        />
      )}
    </motion.div>
  )
}

function EmptyState({ onAdd }) {
  return (
    <div className="p-12 text-center">
      <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-brand-500/10 text-brand-300 mb-3">
        <Users size={26} />
      </div>
      <h3 className="text-white font-display text-lg">No clients yet</h3>
      <p className="text-sm text-slate-400 max-w-md mx-auto mt-1">
        Add your first client to start pre-filling reports automatically.
      </p>
      <button onClick={onAdd} className="btn-primary mt-4">
        <Plus size={14} /> Add Client
      </button>
    </div>
  )
}

function ClientModal({ initial, onClose, onSave }) {
  const [form, setForm] = useState({ ...EMPTY, ...initial })
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const isNew = !initial?.id

  function submit(e) {
    e.preventDefault()
    if (!form.name?.trim()) {
      toast.error('Client name is required')
      return
    }
    onSave({ ...form, name: form.name.trim() })
  }

  // Portal to document.body so the overlay isn't trapped inside an ancestor
  // with `backdrop-filter` (which creates a new containing block for
  // `position: fixed` and would otherwise let the page bleed through).
  return createPortal(
    <div className="fixed inset-0 z-[100] bg-ink-950/70 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
      <motion.form
        initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
        onSubmit={submit}
        className="glass rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto my-auto">
        <div className="flex items-center justify-between p-5 border-b border-white/5 sticky top-0 bg-ink-900/95 backdrop-blur z-10">
          <div className="flex items-center gap-2">
            <Building2 size={16} className="text-brand-300" />
            <h2 className="font-display text-lg text-white">
              {isNew ? 'Add Client' : 'Edit Client'}
            </h2>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white">
            <X size={18} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <Field label="Company / Vessel Owner Name" icon={Building2} required>
            <input className="input" value={form.name} onChange={set('name')}
                   placeholder="WEST SQUADRON MARINE SERVICES PTE LTD" autoFocus />
          </Field>

          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="Contact Person" icon={User}>
              <input className="input" value={form.contact_person} onChange={set('contact_person')}
                     placeholder="Captain Smith" />
            </Field>
            <Field label="Country" icon={Globe}>
              <input className="input" value={form.country} onChange={set('country')}
                     placeholder="Singapore" />
            </Field>
            <Field label="Email" icon={Mail}>
              <input type="email" className="input" value={form.contact_email}
                     onChange={set('contact_email')}
                     placeholder="ops@client.com" />
            </Field>
            <Field label="Phone" icon={Phone}>
              <input className="input" value={form.contact_phone} onChange={set('contact_phone')}
                     placeholder="+65 9123 4567" />
            </Field>
          </div>

          <Field label="Address" icon={MapPin}>
            <textarea className="input" rows={2} value={form.address} onChange={set('address')}
                      placeholder="12 Maritime Rd, Singapore 098765" />
          </Field>

          <Field label="Notes (internal)">
            <textarea className="input" rows={2} value={form.notes} onChange={set('notes')}
                      placeholder="e.g. Net 30 payment terms; prefers PDF reports via secure portal." />
          </Field>
        </div>

        <div className="flex items-center justify-end gap-2 p-4 border-t border-white/5 sticky bottom-0 bg-ink-900/95 backdrop-blur">
          <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
          <button type="submit" className="btn-primary">
            <Save size={14} /> {isNew ? 'Add Client' : 'Save Changes'}
          </button>
        </div>
      </motion.form>
    </div>,
    document.body,
  )
}

function Field({ label, icon: Icon, required, children }) {
  return (
    <label className="block">
      <span className="label flex items-center gap-1">
        {Icon && <Icon size={11} className="text-brand-300" />} {label}
        {required && <span className="text-rose-300 ml-0.5">*</span>}
      </span>
      {children}
    </label>
  )
}
