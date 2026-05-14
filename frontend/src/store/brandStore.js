import { create } from 'zustand'
import { getSettings, fetchLogoObjectUrl } from '../lib/api'
import { useAuth } from './authStore'

/** Singleton store for the *current company's* branding. Re-fetched after login
 *  or after the user edits Settings. The logo is downloaded with auth and
 *  exposed as a blob: URL so <img src> can use it.
 */
export const useBrand = create((set, get) => ({
  loaded: false,
  data: {
    company_name: 'Your Diving Company',
    company_tagline: 'Marine inspection & cleaning services',
    company_address: '',
    company_phone: '',
    company_email: '',
    company_website: '',
    report_footer: 'Powered by NautiCAI',
    has_logo: false,
    logo_url: null,
  },
  logoSrc: null,  // blob: URL (or null)

  /** Pull fresh settings + logo from the backend. No-op without a token. */
  refresh: async () => {
    if (!useAuth.getState().token) {
      set({ loaded: true })
      return
    }
    try {
      const data = await getSettings()
      set({ data, loaded: true })
      // Revoke the previous blob so we don't leak memory
      const prev = get().logoSrc; if (prev) URL.revokeObjectURL(prev)
      const src = data.has_logo ? await fetchLogoObjectUrl() : null
      set({ logoSrc: src })
      // Mirror back to auth.company so all consumers stay in sync
      useAuth.getState().setCompany(data)
    } catch {
      set({ loaded: true })
    }
  },

  /** Merge in fresh settings without re-fetching the logo. */
  setData: (data) => set({ data }),

  reset: () => {
    const prev = get().logoSrc; if (prev) URL.revokeObjectURL(prev)
    set({ logoSrc: null, data: get().data, loaded: true })
  },
}))
