import { useEffect, useState } from 'react'
import { BarChart3, Loader2 } from 'lucide-react'
import {
  BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'
import { getStats } from '../lib/api'
import EmptyState from '../components/EmptyState'

export default function Analysis() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let on = true
    getStats()
      .then((s) => { if (on) setStats(s) })
      .finally(() => { if (on) setLoading(false) })
  }, [])

  const noData = !loading && stats &&
    (!stats.species_mix?.length && !stats.region_index?.length)

  return (
    <div className="space-y-6">
      <header>
        <div className="text-xs uppercase tracking-wider text-brand-300">Analysis</div>
        <h1 className="mt-1 font-display text-2xl font-bold text-white">Fleet Fouling Insights</h1>
        <p className="text-sm text-slate-400">A roll-up of every photo analysed across all your inspections.</p>
      </header>

      {loading ? (
        <div className="glass rounded-2xl py-16 grid place-items-center text-slate-500">
          <Loader2 className="animate-spin" />
        </div>
      ) : noData ? (
        <section className="glass rounded-2xl">
          <EmptyState
            icon={BarChart3}
            title="No analysis data yet"
            hint="Upload underwater images in the Image Studio or run a new inspection — fouling species and per-region indices will populate this view automatically."
          />
        </section>
      ) : (
        <section className="grid lg:grid-cols-2 gap-4">
          <div className="glass rounded-2xl p-5">
            <h3 className="font-display font-semibold text-white">Fouling Species — Frequency</h3>
            <p className="text-xs text-slate-400">Total photos automatically classified.</p>
            <div className="mt-3 h-72">
              <ResponsiveContainer>
                <BarChart data={stats.species_mix} margin={{ left: -20, right: 8, top: 10 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis dataKey="name" stroke="#64748b" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis stroke="#64748b" tickLine={false} axisLine={false} fontSize={12} />
                  <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} contentStyle={tooltipStyle} />
                  <Bar dataKey="value" radius={[8, 8, 0, 0]}>
                    {stats.species_mix.map((d) => (
                      <Bar key={d.name} fill={d.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass rounded-2xl p-5">
            <h3 className="font-display font-semibold text-white">Avg Fouling % per Hull Region</h3>
            <p className="text-xs text-slate-400">Mean across every image classified for each region.</p>
            <div className="mt-3 h-72">
              <ResponsiveContainer>
                <BarChart data={stats.region_index} layout="vertical" margin={{ left: 10, right: 24 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis type="number" stroke="#64748b" tickLine={false} axisLine={false} fontSize={12} />
                  <YAxis dataKey="name" type="category" stroke="#64748b" tickLine={false} axisLine={false} fontSize={12} width={110} />
                  <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} contentStyle={tooltipStyle} />
                  <Bar dataKey="fouling" fill="#22d3ee" radius={[0, 8, 8, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}

const tooltipStyle = {
  background: 'rgba(15,29,58,0.95)', border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 12, color: '#e2e8f0', fontSize: 12,
}
