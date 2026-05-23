import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** Auth state. Persisted to localStorage so a page refresh keeps you logged in. */
export const useAuth = create(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      company: null,

      isAuthed: () => !!get().token,

      setSession: ({ token, user, company }) =>
        set({ token, user, company }),

      setCompany: (company) => set({ company }),

      logout: () => set({ token: null, user: null, company: null }),
    }),
    {
      name: 'nauticai-auth',
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        company: state.company,
      }),
      onRehydrateStorage: () => (_state, err) => {
        if (err) console.warn('auth rehydrate failed', err)
      },
    },
  ),
)
