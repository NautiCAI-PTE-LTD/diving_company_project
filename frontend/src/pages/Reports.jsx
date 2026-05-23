import { useEffect, useMemo, useState } from 'react'
import { format } from 'date-fns'
import { Link } from 'react-router-dom'
import {
  Search, Filter, FileText, Download, Trash2, Loader2, ShipWheel,
  RefreshCw, Sparkles, FilePlus2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  listReports, deleteReport, generateReportPdf, openReportPdf, downloadReportPdf,
} from '../lib/api'
import EmptyState from '../components/EmptyState'

export default function Reports() {
  const [rows, setRows] = useState(null)
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const [busyId, setBusyId] = useState(null)

  const reload = async () => {
    setRows(null)
    try {
      setRows(await listReports())
    } catch (e) {
      toast.error(`Failed to load reports: ${e?.message || e}`)
      setRows([])
    }
  }
  useEffect(() => { reload() }, [])

  const filtered = useMemo(() => {
    if (!rows) return []
    return rows.filter((r) =>
      (filter === 'all' || r.status === filter) &&
      (!q ||
        (r.vesselName || '').toLowerCase().includes(q.toLowerCase()) ||
        (r.jobNo || '').toLowerCase().includes(q.toLowerCase()) ||
        (r.id || '').toLowerCase().includes(q.toLowerCase())),
    )
  }, [rows, q, filter])

  const onGenerate = async (id) => {
    setBusyId(id)
    try {
      await generateReportPdf(id)
      toast.success('PDF generated — opening…')
      try {
        await openReportPdf(id)
      } catch (openErr) {
        toast.error(
          `PDF was built but could not open: ${openErr?.message || openErr}. `
          + 'Use Download on this row, or re-generate after setting the vessel cover on a new report.',
        )
      }
      await reload()
    } catch (e) {
      const msg = e?.response?.data?.detail || e?.message || String(e)
      const hint = /network|ECONNREFUSED|timeout/i.test(msg)
        ? ' — check backend on :8000 and wait for large PDFs to finish.'
        : ''
      toast.error(`PDF build failed: ${msg}${hint}`)
    } finally { setBusyId(null) }
  }

  const onOpen = async (r) => {
    try { await openReportPdf(r.id) }
    catch (e) {
      const msg = e?.message || String(e)
      toast.error(
        msg.includes('not generated') || msg.includes('not found')
          ? `${msg} — click the refresh icon to Generate PDF first.`
          : `Could not open PDF: ${msg}`,
      )
    }
  }
  const onDownload = async (r) => {
    try { await downloadReportPdf(r.id, r.vesselName) }
    catch (e) { toast.error(`Download failed: ${e?.message || e}`) }
  }

  const onDelete = async (id) => {
    if (!confirm(`Delete report ${id}? This cannot be undone.`)) return
    try { await deleteReport(id); toast.success('Report deleted'); await reload() }
    catch (e) { toast.error('Delete failed') }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-brand-300">Reports</div>
          <h1 className="mt-1 font-display text-2xl font-bold text-white">Marine Service Reports</h1>
          <p className="text-sm text-slate-400">Searchable archive of every NautiCAI inspection PDF.</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={reload} title="Refresh"><RefreshCw size={14} /></button>
          <Link to="/new" className="btn-primary"><FilePlus2 size={16} /> New Report</Link>
        </div>
      </header>

      <div className="glass rounded-2xl p-4 flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Search vessel / job / report id"
            className="input pl-9"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-slate-400" />
          {['all', 'completed', 'in_review', 'draft'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`pill ${filter === f ? 'pill-brand' : 'pill-mute'} cursor-pointer`}
            >
              {f.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      <div className="glass rounded-2xl overflow-hidden">
        {rows === null ? (
          <div className="grid place-items-center py-16 text-slate-500">
            <Loader2 className="animate-spin" />
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={FileText}
            title={rows.length === 0 ? 'No reports yet' : 'No matches'}
            hint={rows.length === 0
              ? 'Create your first inspection — once analysed images are attached you can generate a PDF.'
              : 'Try a different search or filter.'}
            action={rows.length === 0 ?
              <Link to="/new" className="btn-primary"><FilePlus2 size={14} /> New Report</Link> : null}
          />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-white/[0.03] text-[11px] uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3 text-left">Report</th>
                <th className="px-4 py-3 text-left">Vessel</th>
                <th className="px-4 py-3 text-left">Job No.</th>
                <th className="px-4 py-3 text-right">Images</th>
                <th className="px-4 py-3 text-left">Severity</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Created</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {filtered.map((r) => (
                <tr key={r.id} className="transition hover:bg-white/[0.03]">
                  <td className="px-4 py-3 font-mono text-xs text-brand-200">{r.id}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 ring-1 ring-white/10">
                        <ShipWheel size={14} className="text-brand-300" />
                      </div>
                      <div>
                        <div className="font-semibold text-white">{r.vesselName || '—'}</div>
                        <div className="text-[11px] text-slate-400">{r.vesselType || ''}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-300">{r.jobNo || '—'}</td>
                  <td className="px-4 py-3 text-right text-slate-300">{r.images}</td>
                  <td className="px-4 py-3">
                    <span className={`pill ${r.severity === 'C' ? 'pill-warn' : r.severity === 'B' ? 'pill-brand' : 'pill-success'}`}>
                      Sev {r.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`pill ${r.status === 'completed' ? 'pill-success' : r.status === 'draft' ? 'pill-mute' : 'pill-brand'}`}>
                      {r.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-300">{format(new Date(r.createdAt), 'dd MMM yyyy HH:mm')}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex gap-1">
                      <button
                        onClick={() => onGenerate(r.id)}
                        disabled={busyId === r.id}
                        title={r.pdf_url ? 'Re-generate PDF' : 'Generate PDF'}
                        className="rounded-lg bg-white/5 p-1.5 text-brand-300 hover:bg-white/10 disabled:opacity-50">
                        {busyId === r.id ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                      </button>
                      {r.pdf_url && (
                        <button onClick={() => onDownload(r)} title="Download PDF"
                                className="rounded-lg bg-white/5 p-1.5 text-brand-300 hover:bg-white/10">
                          <Download size={14} />
                        </button>
                      )}
                      {r.pdf_url && (
                        <button onClick={() => onOpen(r)} title="Open PDF in new tab"
                                className="rounded-lg bg-white/5 p-1.5 text-brand-300 hover:bg-white/10">
                          <FileText size={14} />
                        </button>
                      )}
                      <button onClick={() => onDelete(r.id)} title="Delete"
                              className="rounded-lg bg-white/5 p-1.5 text-rose-300 hover:bg-white/10">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
