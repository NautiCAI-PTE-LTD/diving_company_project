import * as Icons from 'lucide-react'
import clsx from 'clsx'
import ImageDropzone from './ImageDropzone'
import { Trash2, ScanSearch, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'

export default function RegionTile({ region, items = [], onAdd, onRemove, onAnalyze }) {
  const Icon = Icons[region.icon] || Icons.Image
  const done = items.filter((i) => i.status === 'done').length

  return (
    <section className="glass rounded-2xl p-4 sm:p-5">
      <header className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-white/5 p-2 ring-1 ring-white/10">
            <Icon size={18} className="text-brand-300" />
          </div>
          <div>
            <h3 className="font-display text-sm font-bold text-white">{region.displayLabel}</h3>
            <div className="text-[11px] text-slate-400">
              {items.length} image{items.length === 1 ? '' : 's'} · {done} analysed
            </div>
          </div>
        </div>
        <div className="pill-mute">{region.id}</div>
      </header>

      <ImageDropzone compact acceptVideo={false} onFiles={onAdd} />

      {items.length > 0 && (
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-3">
          {items.map((img) => (
            <ImageThumb key={img.id} img={img} onRemove={() => onRemove(img.id)} onAnalyze={() => onAnalyze(img.id)} />
          ))}
        </div>
      )}
    </section>
  )
}

function ImageThumb({ img, onRemove, onAnalyze }) {
  return (
    <div className="group relative overflow-hidden rounded-xl border border-white/10 bg-ink-900">
      <img src={img.url} alt={img.name} className="aspect-square h-full w-full object-cover transition group-hover:scale-105" />

      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink-950 via-ink-950/40 to-transparent opacity-90" />

      {/* Status badge */}
      <div className="absolute left-2 top-2">
        {img.status === 'pending'   && <span className="pill-mute"><AlertCircle size={11} /> Pending</span>}
        {img.status === 'analyzing' && <span className="pill-brand"><Loader2 size={11} className="animate-spin" /> Analysing</span>}
        {img.status === 'done'      && <span className="pill-success"><CheckCircle2 size={11} /> Done</span>}
        {img.status === 'error'     && <span className="pill-warn"><AlertCircle size={11} /> Error</span>}
      </div>

      {/* Hover actions */}
      <div className="absolute right-2 top-2 flex gap-1 opacity-0 transition group-hover:opacity-100">
        <button onClick={onAnalyze} className="rounded-lg bg-ink-900/80 p-1.5 text-brand-300 hover:bg-ink-800" title="Analyse">
          <ScanSearch size={14} />
        </button>
        <button onClick={onRemove} className="rounded-lg bg-ink-900/80 p-1.5 text-rose-300 hover:bg-ink-800" title="Remove">
          <Trash2 size={14} />
        </button>
      </div>

      {/* Footer info */}
      <div className="absolute inset-x-0 bottom-0 p-2.5 text-[11px]">
        <div className="truncate font-semibold text-white">{img.name}</div>
        {img.result && (
          <div className="mt-1 flex flex-wrap gap-1">
            <span className="pill-brand">{img.result.species?.top || '—'}</span>
            <span className="pill-mute">{Math.round((img.result.fouling_pct || 0))}%</span>
          </div>
        )}
      </div>
    </div>
  )
}
