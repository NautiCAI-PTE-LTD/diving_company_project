import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ShipWheel, Activity, Camera, FileCheck2, Sparkles, AlertTriangle,
  TrendingUp, ChevronRight, Anchor, Inbox, Loader2,
} from 'lucide-react'
import StatCard from '../components/StatCard'
import EmptyState from '../components/EmptyState'
import {
  ResponsiveContainer, AreaChart, Area, Tooltip, XAxis, YAxis, CartesianGrid,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import { getStats, openReportPdf } from '../lib/api'
import { useBrand } from '../store/brandStore'
import { format } from 'date-fns'

export default function Dashboard() {
  const brand = useBrand((s) => s.data)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let on = true
    setLoading(true)
    getStats()
      .then((s) => { if (on) setStats(s) })
      .catch((e) => { if (on) setErr(e.message || 'Failed to load stats') })
      .finally(() => { if (on) setLoading(false) })
    return () => { on = false }
  }, [])

  const empty = !loading && stats &&
    stats.images_processed === 0 && stats.reports_generated === 0

  return (
    <div className="space-y-6">
      {/* Hero */}
      <motion.section
        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl border border-white/10 bg-ocean-gradient p-6 sm:p-10"
      >
        <div className="absolute inset-0 bg-grid-faint bg-grid-faint opacity-30" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-wave-pattern bg-no-repeat bg-bottom opacity-60" />
        <div className="relative grid lg:grid-cols-[1.4fr_1fr] gap-8">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-brand-400/30 bg-brand-400/10 px-3 py-1 text-xs font-semibold text-brand-200">
              <Sparkles size={12} /> AI-Powered Marine Documentation
            </div>
            <h1 className="mt-4 font-display text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-white">
              Inspect deeper.<br />
              <span className="bg-gradient-to-r from-brand-200 to-accent-400 bg-clip-text text-transparent">
                Report faster.
              </span>
            </h1>
            <p className="mt-3 max-w-xl text-sm sm:text-base text-slate-300">
              Drop raw underwater photos — NautiCAI auto-classifies the hull region, compares before / after cleaning,
              quantifies fouling species, and assembles a class-society-ready PDF in seconds.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/new" className="btn-primary">
                <Anchor size={16} /> Start New Inspection
              </Link>
              <Link to="/reports" className="btn-ghost">
                Browse reports <ChevronRight size={14} />
              </Link>
            </div>
          </div>

          {/* Client branding + automation panel */}
          <div className="glass-strong rounded-2xl p-5 self-start">
            <div className="flex items-center justify-between">
              <div className="text-xs uppercase tracking-wider text-slate-400">Automations</div>
              <span className="pill-success">All Online</span>
            </div>
            <div className="mt-4 space-y-3">
              {[
                { n: 'Hull Zone Detector',     m: 'Sorts photos into 11 hull regions automatically' },
                { n: 'Cleaning Stage Detector',m: 'Separates before-cleaning vs after-cleaning photos' },
                { n: 'Fouling Identifier',     m: 'Tags algae, barnacles, macroalgae, mussels, clean paint' },
                { n: 'Vessel-Name Reader',     m: 'Reads vessel name from a deck photo' },
              ].map((row) => (
                <div key={row.n} className="flex items-center gap-3 rounded-xl bg-white/[0.03] p-3 ring-1 ring-white/10">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-400/15 text-brand-300">
                    <Activity size={16} />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-white">{row.n}</div>
                    <div className="truncate text-[11px] text-slate-400">{row.m}</div>
                  </div>
                  <span className="ml-auto h-2 w-2 rounded-full bg-success-500 shadow-[0_0_10px_2px_rgba(16,185,129,0.6)]" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </motion.section>

      {/* KPIs (real) */}
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard icon={ShipWheel}     label="Vessels Inspected" value={loading ? '—' : stats?.vessels_inspected ?? 0} tone="brand"   />
        <StatCard icon={Camera}        label="Images Processed"  value={loading ? '—' : stats?.images_processed ?? 0}  tone="success" />
        <StatCard icon={FileCheck2}    label="Reports Generated" value={loading ? '—' : stats?.reports_generated ?? 0} tone="brand"   />
        <StatCard icon={AlertTriangle} label="Avg Fouling Index" value={loading ? '—' : (stats?.avg_fouling ?? 0)} suffix="%" tone="warm" />
      </section>

      {err && (
        <div className="glass rounded-2xl p-4 text-sm text-rose-300">
          Failed to load stats: {err}. Make sure the backend is running on <code>:8000</code>.
        </div>
      )}

      {empty ? (
        <section className="glass rounded-2xl">
          <EmptyState
            icon={Inbox}
            title="No inspection data yet"
            hint="Upload underwater photos in the Image Studio or start a new inspection — the dashboard will populate automatically."
            action={
              <Link to="/new" className="btn-primary"><Anchor size={14} /> Start New Inspection</Link>
            }
          />
        </section>
      ) : (
        <>
          {/* Charts (real) */}
          <section className="grid gap-4 lg:grid-cols-3">
            <div className="glass rounded-2xl p-5 lg:col-span-2">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-display font-semibold text-white">Inspection Activity</h3>
                  <p className="text-xs text-slate-400">Past 6 months · across fleet</p>
                </div>
                <div className="flex items-center gap-2 text-emerald-300 text-xs font-semibold">
                  <TrendingUp size={14} /> live
                </div>
              </div>
              <div className="mt-4 h-64">
                {loading ? <ChartSkeleton /> : (
                  <ResponsiveContainer>
                    <AreaChart data={stats?.activity || []} margin={{ left: -20, right: 8, top: 10 }}>
                      <defs>
                        <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%"   stopColor="#22d3ee" stopOpacity={0.55} />
                          <stop offset="100%" stopColor="#22d3ee" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="g2" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%"   stopColor="#f59e0b" stopOpacity={0.4} />
                          <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                      <XAxis dataKey="m" stroke="#64748b" tickLine={false} axisLine={false} fontSize={12} />
                      <YAxis stroke="#64748b" tickLine={false} axisLine={false} fontSize={12} />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Area type="monotone" dataKey="inspections" stroke="#22d3ee" fill="url(#g1)" strokeWidth={2} name="Inspections" />
                      <Area type="monotone" dataKey="foulingIdx"  stroke="#f59e0b" fill="url(#g2)" strokeWidth={2} name="Fouling Idx" />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>

            <div className="glass rounded-2xl p-5">
              <h3 className="font-display font-semibold text-white">Fouling Species Mix</h3>
              <p className="text-xs text-slate-400">Photos analysed across all jobs</p>
              <div className="mt-2 h-64">
                {loading ? <ChartSkeleton /> : (stats?.species_mix?.length ? (
                  <ResponsiveContainer>
                    <PieChart>
                      <Pie data={stats.species_mix} innerRadius={48} outerRadius={80} paddingAngle={3}
                           dataKey="value" stroke="rgba(7,13,26,0.9)" strokeWidth={2}>
                        {stats.species_mix.map((d) => <Cell key={d.name} fill={d.color} />)}
                      </Pie>
                      <Tooltip contentStyle={tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 11, color: '#cbd5e1' }} iconType="circle" />
                    </PieChart>
                  </ResponsiveContainer>
                ) : <CenterMute>No species data yet.</CenterMute>)}
              </div>
            </div>
          </section>

          {/* Recent inspections (real) */}
          <section className="glass rounded-2xl p-5">
            <div className="flex items-center justify-between">
              <h3 className="font-display font-semibold text-white">Recent Inspections</h3>
              <Link to="/reports" className="text-xs font-semibold text-brand-300 hover:text-brand-200">
                View all →
              </Link>
            </div>
            <div className="mt-4 overflow-hidden rounded-xl border border-white/10">
              <table className="w-full text-sm">
                <thead className="bg-white/[0.03] text-[11px] uppercase tracking-wider text-slate-400">
                  <tr>
                    <th className="px-4 py-3 text-left">Report</th>
                    <th className="px-4 py-3 text-left">Vessel</th>
                    <th className="px-4 py-3 text-left">Job No.</th>
                    <th className="px-4 py-3 text-left">Severity</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-left">Created</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {(stats?.recent || []).length === 0 && (
                    <tr><td colSpan={7} className="px-4 py-6 text-center text-slate-500">No reports created yet.</td></tr>
                  )}
                  {(stats?.recent || []).map((r) => (
                    <tr key={r.id} className="transition hover:bg-white/[0.03]">
                      <td className="px-4 py-3 font-mono text-xs text-brand-200">{r.id}</td>
                      <td className="px-4 py-3 font-semibold text-white">{r.vesselName || '—'}</td>
                      <td className="px-4 py-3 text-slate-300">{r.jobNo || '—'}</td>
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
                      <td className="px-4 py-3 text-slate-300">{format(new Date(r.createdAt), 'dd MMM yyyy')}</td>
                      <td className="px-4 py-3 text-right">
                        {r.pdf_url ? (
                          <button onClick={() => openReportPdf(r.id)}
                                  className="text-xs font-semibold text-brand-300 hover:text-brand-200">
                            Open PDF →
                          </button>
                        ) : (
                          <Link to="/reports" className="text-xs font-semibold text-brand-300 hover:text-brand-200">
                            Open →
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}

const tooltipStyle = {
  background: 'rgba(15,29,58,0.95)', border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 12, color: '#e2e8f0', fontSize: 12,
}

function ChartSkeleton() {
  return (
    <div className="grid h-full place-items-center text-slate-500 text-xs">
      <Loader2 className="animate-spin" />
    </div>
  )
}

function CenterMute({ children }) {
  return <div className="grid h-full place-items-center text-xs text-slate-500">{children}</div>
}
