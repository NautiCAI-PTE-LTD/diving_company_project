import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** Auth state. Persisted to localStorage so a page refresh keeps you logged in.
 *
 *  Shape:
 *    token     : JWT string (added to every axios call by an interceptor)
 *    user      : { id, email, full_name, role, company_id }
 *    company   : SettingsModel (company_name, has_logo, logo_url, …)
 *    hydrated  : true once the persist layer has loaded from localStorage
 */
export const useAuth = create(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      company: null,
      hydrated: false,

      isAuthed: () => !!get().token,

      setSession: ({ token, user, company }) =>
        set({ token, user, company }),

      setCompany: (company) => set({ company }),

      logout: () => set({ token: null, user: null, company: null }),
    }),
    {
      name: 'nauticai-auth',
      onRehydrateStorage: () => (state) => {
        if (state) state.hydrated = true
      },
    },
  ),
)
