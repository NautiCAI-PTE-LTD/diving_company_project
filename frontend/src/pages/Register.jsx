import { useState, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import {
  Mail, Lock, Loader2, ArrowRight, ArrowLeft, Building2,
  User as UserIcon, Phone, Globe, MapPin, Hash, Calendar, Shield,
  FileSignature, Image as ImageIcon, Upload, X, Check, ChevronRight,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  register as registerApi, uploadLogo,
} from '../lib/api'
import { useAuth } from '../store/authStore'
import { useBrand } from '../store/brandStore'
import AuthLayout from '../components/AuthLayout'
import clsx from 'clsx'

const CLASS_SOCIETIES = [
  'BV', 'DNV', 'ABS', 'LR', 'NK', 'KR', 'CCS', 'IRS', 'RINA', 'PRS', 'IACS', 'INSB',
]

export default function Register() {
  const nav = useNavigate()
  const setSession = useAuth((s) => s.setSession)
  const refreshBrand = useBrand((s) => s.refresh)

  const [step, setStep] = useState(0)
  const [form, setForm] = useState({
    // step 1 — account
    company_name: '', full_name: '', email: '', password: '',
    // step 2 — company profile
    tagline: '', address: '', country: '', phone: '', website: '',
    registration_number: '', tax_number: '', established_year: '',
    class_approvals: [],
    diving_certifications: '',
    insurance: '',
  })
  const [logoFile, setLogoFile] = useState(null)
  const [logoPreview, setLogoPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const onSet = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const step1Valid = useMemo(
    () => form.company_name.trim().length >= 2 && form.full_name.trim().length >= 1
       && /.+@.+\..+/.test(form.email) && form.password.length >= 6,
    [form],
  )

  // -------- step 1 → step 2 --------
  const goNext = () => {
    if (!step1Valid) {
      toast.error('Please fill name, email and a password (6+ chars).'); return
    }
    setStep(1)
  }

  // -------- logo dropzone (step 2) --------
  const onDrop = (files) => {
    const f = files[0]; if (!f) return
    setLogoFile(f)
    setLogoPreview(URL.createObjectURL(f))
  }
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'image/*': ['.png', '.jpg', '.jpeg', '.webp', '.svg'] },
    multiple: false, maxSize: 5 * 1024 * 1024, onDrop,
  })
  const removeLogo = () => {
    if (logoPreview) URL.revokeObjectURL(logoPreview)
    setLogoFile(null); setLogoPreview(null)
  }
  const toggleApproval = (s) => setForm((f) => ({
    ...f,
    class_approvals: f.class_approvals.includes(s)
      ? f.class_approvals.filter((x) => x !== s)
      : [...f.class_approvals, s],
  }))

  // -------- submit (creates account + uploads logo) --------
  const submit = async (skipExtras = false) => {
    setBusy(true)
    try {
      const payload = skipExtras
        ? {
            company_name: form.company_name, full_name: form.full_name,
            email: form.email, password: form.password,
          }
        : form
      const r = await registerApi(payload)
      setSession({ token: r.access_token, user: r.user, company: r.company })

      // Upload logo while the new JWT is in place (axios interceptor adds it).
      if (!skipExtras && logoFile) {
        try { await uploadLogo(logoFile) }
        catch (e) { toast.error('Logo upload failed — you can retry in Settings.') }
      }
      await refreshBrand()
      toast.success(`Welcome ${r.company.company_name}!`)
      nav(skipExtras ? '/settings' : '/', { replace: true })
    } catch (err) {
      const det = err?.response?.data?.detail
      const msg = Array.isArray(det) ? det.map((d) => d.msg).join(', ')
        : (det || err?.message || 'Registration failed')
      toast.error(msg)
    } finally { setBusy(false) }
  }

  return (
    <AuthLayout
      title={step === 0 ? 'Create your workspace' : 'Set up your company profile'}
      subtitle={step === 0
        ? 'One account per diving company. Inspections, reports and branding are kept private.'
        : 'These details flow straight onto every PDF report — you won\'t have to re-enter them.'}>

      <WizardDots step={step} />

      {step === 0 ? (
        <form onSubmit={(e) => { e.preventDefault(); goNext() }} className="space-y-4">
          <label className="block">
            <span className="label flex items-center gap-1.5"><Building2 size={12} /> Company Name</span>
            <input className="input" required minLength={2}
                   value={form.company_name} onChange={onSet('company_name')}
                   placeholder="e.g. Atlantic Dive Services" />
          </label>

          <div className="grid sm:grid-cols-2 gap-3">
            <label className="block">
              <span className="label flex items-center gap-1.5"><UserIcon size={12} /> Your Name</span>
              <input className="input" required value={form.full_name}
                     onChange={onSet('full_name')} placeholder="Jane Captain" />
            </label>
            <label className="block">
              <span className="label flex items-center gap-1.5"><Mail size={12} /> Work Email</span>
              <input className="input" type="email" required value={form.email}
                     onChange={onSet('email')} placeholder="you@yourcompany.com" />
            </label>
          </div>

          <label className="block">
            <span className="label flex items-center gap-1.5"><Lock size={12} /> Password</span>
            <input className="input" type="password" required minLength={6}
                   autoComplete="new-password"
                   value={form.password} onChange={onSet('password')}
                   placeholder="At least 6 characters" />
          </label>

          <button type="submit" disabled={!step1Valid || busy} className="btn-primary w-full mt-2">
            Continue <ChevronRight size={16} />
          </button>
        </form>
      ) : (
        <div className="space-y-5">
          {/* logo dropzone */}
          <div>
            <div className="label flex items-center gap-1.5 mb-2">
              <ImageIcon size={12} /> Company Logo
            </div>
            <div {...getRootProps()}
                 className={clsx(
                   'relative cursor-pointer overflow-hidden rounded-2xl border-2 border-dashed transition',
                   isDragActive ? 'border-brand-400 bg-brand-400/10'
                                : 'border-white/15 bg-white/[0.02] hover:border-brand-400/60',
                   'min-h-[120px] grid place-items-center text-center p-3',
                 )}>
              <input {...getInputProps()} />
              {logoPreview ? (
                <div className="flex items-center gap-3 w-full">
                  <div className="rounded-xl bg-white/95 p-2 ring-1 ring-white/20">
                    <img src={logoPreview} alt="logo" className="h-16 max-w-[140px] object-contain" />
                  </div>
                  <div className="flex-1 text-left">
                    <div className="text-xs text-emerald-300 flex items-center gap-1">
                      <Check size={12} /> Ready to upload
                    </div>
                    <div className="text-[11px] text-slate-400 truncate">{logoFile?.name}</div>
                  </div>
                  <button type="button" onClick={(e) => { e.stopPropagation(); removeLogo() }}
                          className="btn-ghost !px-2"><X size={14} /></button>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-1">
                  <Upload size={18} className="text-brand-300" />
                  <div className="text-sm font-semibold text-white">Drop your company logo</div>
                  <div className="text-[11px] text-slate-400">PNG / JPG / SVG · appears top-left of every report</div>
                </div>
              )}
            </div>
          </div>

          {/* basic contact */}
          <Section title="Contact details">
            <label className="block">
              <span className="label flex items-center gap-1.5"><FileSignature size={12} /> Tagline</span>
              <input className="input" value={form.tagline} onChange={onSet('tagline')}
                     placeholder="Marine inspection & hull cleaning since 1998" />
            </label>
            <div className="grid sm:grid-cols-2 gap-3">
              <label className="block">
                <span className="label flex items-center gap-1.5"><MapPin size={12} /> Address</span>
                <input className="input" value={form.address} onChange={onSet('address')}
                       placeholder="12 Harbour Rd, Singapore" />
              </label>
              <label className="block">
                <span className="label flex items-center gap-1.5"><Globe size={12} /> Country</span>
                <input className="input" value={form.country} onChange={onSet('country')}
                       placeholder="Singapore" />
              </label>
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <label className="block">
                <span className="label flex items-center gap-1.5"><Phone size={12} /> Phone</span>
                <input className="input" value={form.phone} onChange={onSet('phone')} />
              </label>
              <label className="block">
                <span className="label flex items-center gap-1.5"><Globe size={12} /> Website</span>
                <input className="input" value={form.website} onChange={onSet('website')}
                       placeholder="https://yourcompany.com" />
              </label>
            </div>
          </Section>

          {/* compliance / legal */}
          <Section title="Compliance & legal">
            <div className="grid sm:grid-cols-3 gap-3">
              <label className="block">
                <span className="label flex items-center gap-1.5"><Hash size={12} /> Registration No.</span>
                <input className="input" value={form.registration_number} onChange={onSet('registration_number')} />
              </label>
              <label className="block">
                <span className="label flex items-center gap-1.5"><Hash size={12} /> Tax / VAT No.</span>
                <input className="input" value={form.tax_number} onChange={onSet('tax_number')} />
              </label>
              <label className="block">
                <span className="label flex items-center gap-1.5"><Calendar size={12} /> Established</span>
                <input className="input" value={form.established_year} onChange={onSet('established_year')}
                       placeholder="1998" />
              </label>
            </div>
            <label className="block">
              <span className="label flex items-center gap-1.5"><Shield size={12} /> Diving Safety Standards</span>
              <input className="input" value={form.diving_certifications} onChange={onSet('diving_certifications')}
                     placeholder="IMCA D 014, ADCI Consensus Standard" />
            </label>
            <label className="block">
              <span className="label flex items-center gap-1.5"><Shield size={12} /> Insurance</span>
              <input className="input" value={form.insurance} onChange={onSet('insurance')}
                     placeholder="Underwriter & policy reference" />
            </label>
          </Section>

          {/* class approvals — multi-select chips */}
          <Section title="Class society approvals (optional)">
            <p className="text-[11px] text-slate-400 -mt-1">
              Tap the societies your company is approved by. They will appear on the report cover.
            </p>
            <div className="flex flex-wrap gap-2 mt-2">
              {CLASS_SOCIETIES.map((s) => {
                const on = form.class_approvals.includes(s)
                return (
                  <button key={s} type="button" onClick={() => toggleApproval(s)}
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
          </Section>

          {/* actions */}
          <div className="flex items-center justify-between gap-3 pt-2">
            <button type="button" onClick={() => setStep(0)} className="btn-ghost">
              <ArrowLeft size={14} /> Back
            </button>
            <div className="flex gap-2">
              <button type="button" onClick={() => submit(true)} disabled={busy}
                      className="btn-outline text-xs">
                Skip & set up later
              </button>
              <button type="button" onClick={() => submit(false)} disabled={busy}
                      className="btn-primary">
                {busy ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
                Create Workspace
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="mt-6 pt-6 border-t border-white/5 text-center text-sm text-slate-400">
        Already have an account?{' '}
        <Link to="/login" className="text-brand-300 hover:text-brand-200 font-semibold">
          Sign in
        </Link>
      </div>
    </AuthLayout>
  )
}

function Section({ title, children }) {
  return (
    <div className="rounded-xl bg-white/[0.02] ring-1 ring-white/5 p-4 space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-300">{title}</div>
      {children}
    </div>
  )
}

function WizardDots({ step }) {
  return (
    <div className="flex items-center gap-2 mb-6">
      {[0, 1].map((i) => (
        <div key={i} className={clsx(
          'flex-1 h-1.5 rounded-full transition',
          i <= step ? 'bg-brand-400' : 'bg-white/10',
        )} />
      ))}
      <span className="text-[10px] uppercase tracking-wider text-slate-400 ml-2">
        Step {step + 1} of 2
      </span>
    </div>
  )
}
