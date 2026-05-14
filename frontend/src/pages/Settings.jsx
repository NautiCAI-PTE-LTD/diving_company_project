import { useEffect, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  Building2, Image as ImageIcon, Save, Trash2, Upload, Loader2,
  Activity, Mail, Phone, Globe, MapPin, FileSignature, Shield, Hash,
  Calendar,
} from 'lucide-react'
import clsx from 'clsx'
import toast from 'react-hot-toast'
import {
  getSettings, saveSettings, uploadLogo, deleteLogo,
} from '../lib/api'
import { useBrand } from '../store/brandStore'

const CONTACT_FIELDS = [
  { key: 'company_name',    label: 'Company Name',  icon: Building2,     ph: 'e.g. Atlantic Dive Services' },
  { key: 'company_tagline', label: 'Tagline',       icon: FileSignature, ph: 'Underwater inspection & hull cleaning' },
  { key: 'company_address', label: 'Address',       icon: MapPin,        ph: 'Street, City' },
  { key: 'country',         label: 'Country',       icon: Globe,         ph: 'Singapore' },
  { key: 'company_phone',   label: 'Phone',         icon: Phone,         ph: '+1 555 123 4567' },
  { key: 'company_email',   label: 'Email',         icon: Mail,          ph: 'ops@yourcompany.com' },
  { key: 'company_website', label: 'Website',       icon: Globe,         ph: 'https://yourcompany.com' },
  { key: 'established_year',label: 'Established',   icon: Calendar,      ph: '1998' },
]

const COMPLIANCE_FIELDS = [
  { key: 'registration_number',   label: 'Registration No.',          icon: Hash,         ph: 'Business registration number' },
  { key: 'tax_number',            label: 'Tax / VAT No.',             icon: Hash,         ph: 'VAT / GST / EIN' },
  { key: 'diving_certifications', label: 'Diving Safety Standards',   icon: Shield,       ph: 'IMCA D 014, ADCI…' },
  { key: 'insurance',             label: 'Insurance',                 icon: Shield,       ph: 'Underwriter & policy reference' },
  { key: 'report_prefix',         label: 'Report Number Prefix',      icon: FileSignature,ph: 'NAUTICAI-REP' },
  { key: 'report_footer',         label: 'Report Footer Text',        icon: FileSignature,ph: 'Powered by NautiCAI' },
]

const CLASS_SOCIETIES = [
  'BV', 'DNV', 'ABS', 'LR', 'NK', 'KR', 'CCS', 'IRS', 'RINA', 'PRS', 'IACS', 'INSB',
]

export default function Settings() {
  const brand = useBrand()
  const [form, setForm] = useState(brand.data)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)

  useEffect(() => {
    (async () => {
      const data = await getSettings()
      setForm(data); brand.setData(data)
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const refreshBrand = brand.refresh

  const onChange = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const onSave = async () => {
    setSaving(true)
    try {
      const data = await saveSettings(form)
      setForm(data); brand.setData(data)
      toast.success('Branding saved')
    } catch (e) {
      toast.error(`Save failed: ${e?.message || e}`)
    } finally { setSaving(false) }
  }

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'image/*': ['.png', '.jpg', '.jpeg', '.webp', '.svg'] },
    multiple: false, maxSize: 5 * 1024 * 1024,
    onDrop: async (files) => {
      const f = files[0]; if (!f) return
      setUploading(true)
      try {
        const data = await uploadLogo(f)
        setForm(data); brand.setData(data)
        await refreshBrand()
        toast.success('Logo updated')
      } catch (e) {
        toast.error(`Upload failed: ${e?.message || e}`)
      } finally { setUploading(false) }
    },
  })

  const onRemoveLogo = async () => {
    if (!confirm('Remove your company logo?')) return
    try {
      const data = await deleteLogo()
      setForm(data); brand.setData(data)
      await refreshBrand()
      toast.success('Logo removed')
    } catch (e) { toast.error('Remove failed') }
  }

  return (
    <div className="space-y-6">
      <header>
        <div className="text-xs uppercase tracking-wider text-brand-300">Settings</div>
        <h1 className="mt-1 font-display text-2xl font-bold text-white">Workspace & Branding</h1>
        <p className="text-sm text-slate-400">
          Set your company name and logo. They appear top-left of every report and across the dashboard.
        </p>
      </header>

      <section className="grid lg:grid-cols-5 gap-4">
        {/* Logo upload */}
        <div className="glass rounded-2xl p-5 lg:col-span-2">
          <div className="flex items-center gap-2 mb-4">
            <ImageIcon size={16} className="text-brand-300" />
            <h3 className="font-display font-semibold text-white">Company Logo</h3>
          </div>

          <div
            {...getRootProps()}
            className={clsx(
              'relative cursor-pointer overflow-hidden rounded-2xl border-2 border-dashed transition',
              isDragActive ? 'border-brand-400 bg-brand-400/10' : 'border-white/15 bg-white/[0.02] hover:border-brand-400/60',
              'min-h-[220px] grid place-items-center text-center p-4',
            )}>
            <input {...getInputProps()} />
            {form.has_logo && brand.logoSrc ? (
              <div className="flex flex-col items-center gap-3">
                <div className="rounded-2xl bg-white/95 p-3 ring-1 ring-white/20">
                  <img src={brand.logoSrc} alt="logo" className="h-24 max-w-[180px] object-contain" />
                </div>
                <div className="text-[11px] text-slate-400">{form.company_name}</div>
                <div className="text-[10px] text-slate-500">Drop a new file to replace · PNG / JPG / SVG</div>
              </div>
            ) : uploading ? (
              <Loader2 className="animate-spin text-brand-300" />
            ) : (
              <div className="flex flex-col items-center gap-2">
                <Upload size={22} className="text-brand-300" />
                <div className="text-sm font-semibold text-white">Drop your company logo</div>
                <div className="text-[11px] text-slate-400">PNG / JPG / SVG · square works best</div>
              </div>
            )}
          </div>

          {form.has_logo && (
            <button onClick={onRemoveLogo} className="btn-ghost w-full mt-3 text-rose-300">
              <Trash2 size={14} /> Remove logo
            </button>
          )}
          <p className="mt-3 text-[11px] text-slate-500">
            The logo is used top-left of every report and in the sidebar. NautiCAI branding stays on
            the top-right.
          </p>
        </div>

        {/* Company details (contact + compliance + class approvals) */}
        <div className="glass rounded-2xl p-5 lg:col-span-3 space-y-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Building2 size={16} className="text-brand-300" />
              <h3 className="font-display font-semibold text-white">Company Details</h3>
            </div>
            <button onClick={onSave} disabled={saving} className="btn-primary">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Save
            </button>
          </div>

          <SettingsBlock title="Contact & identity">
            <div className="grid sm:grid-cols-2 gap-3">
              {CONTACT_FIELDS.map(({ key, label, icon: Icon, ph }) => (
                <label key={key} className="block">
                  <span className="label flex items-center gap-1.5"><Icon size={12} /> {label}</span>
                  <input className="input" value={form[key] || ''} onChange={onChange(key)} placeholder={ph} />
                </label>
              ))}
            </div>
          </SettingsBlock>

          <SettingsBlock title="Compliance & legal (appears on the report cover)">
            <div className="grid sm:grid-cols-2 gap-3">
              {COMPLIANCE_FIELDS.map(({ key, label, icon: Icon, ph }) => (
                <label key={key} className="block">
                  <span className="label flex items-center gap-1.5"><Icon size={12} /> {label}</span>
                  <input className="input" value={form[key] || ''} onChange={onChange(key)} placeholder={ph} />
                </label>
              ))}
            </div>
          </SettingsBlock>

          <SettingsBlock title="Class society approvals">
            <p className="text-[11px] text-slate-400">
              Pick the classification societies your company is approved by. They print on the report cover.
            </p>
            <div className="flex flex-wrap gap-2 mt-2">
              {CLASS_SOCIETIES.map((s) => {
                const on = (form.class_approvals || []).includes(s)
                return (
                  <button key={s} type="button"
                    onClick={() => setForm((f) => {
                      const cur = f.class_approvals || []
                      return {
                        ...f,
                        class_approvals: cur.includes(s)
                          ? cur.filter((x) => x !== s) : [...cur, s],
                      }
                    })}
                    className={clsx(
                      'rounded-full px-3 py-1 text-xs font-semibold ring-1 transition',
                      on ? 'bg-brand-500 ring-brand-400 text-white shadow-glow'
                         : 'bg-white/5 ring-white/15 text-slate-300 hover:ring-brand-400/40',
                    )}>
                    {s}
                  </button>
                )
              })}
            </div>
          </SettingsBlock>
        </div>
      </section>

      {/* AI capabilities panel — client-friendly language only */}
      <section className="glass rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Activity size={16} className="text-brand-300" />
          <h3 className="font-display font-semibold text-white">Automation Capabilities</h3>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { t: 'Hull Zone Detector',    s: 'Recognises 11 hull zones from photos (bow, propeller, rudder, bilge keel, sea chest…)' },
            { t: 'Cleaning Stage Detector', s: 'Tells before-cleaning from after-cleaning photos automatically.' },
            { t: 'Fouling Identifier',   s: 'Spots algae, barnacles, macroalgae, mussels and clean paint per photo.' },
            { t: 'Vessel-Name Reader',   s: 'Reads the painted vessel name on bow/stern photos to auto-fill the report.' },
          ].map((row) => (
            <div key={row.t} className="rounded-xl bg-white/[0.03] p-3 ring-1 ring-white/10">
              <div className="text-sm font-semibold text-white">{row.t}</div>
              <div className="mt-1 text-[11px] text-slate-400">{row.s}</div>
              <div className="mt-2 inline-flex items-center gap-1 text-emerald-300 text-[10px] uppercase tracking-wider font-semibold">
                <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(16,185,129,0.7)]" /> Active
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function SettingsBlock({ title, children }) {
  return (
    <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-4 space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-300">{title}</div>
      {children}
    </div>
  )
}
