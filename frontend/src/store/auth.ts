import { create } from "zustand";
import { persist } from "zustand/middleware";
import { api } from "@/lib/api";
import type { UserProfile } from "@/lib/api";

interface AuthState {
  token: string | null;
  userProfile: UserProfile | null;
  isLoading: boolean;
  isHydrated: boolean;
  error: string | null;
  setToken: (token: string | null) => void;
  setUserProfile: (profile: UserProfile | null) => void;
  setError: (error: string | null) => void;
  setHydrated: (hydrated: boolean) => void;
  setLoading: (loading: boolean) => void;
  login: () => void;
  logout: () => void;
  fetchUserProfile: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      userProfile: null,
      isLoading: false,
      isHydrated: false,
      error: null,

      setToken: (token) => set({ token }),
      setUserProfile: (profile) => set({ userProfile: profile }),
      setError: (error) => set({ error }),
      setHydrated: (hydrated) => set({ isHydrated: hydrated }),
      setLoading: (loading) => set({ isLoading: loading }),

      login: () => {
        // Redirect to Clio OAuth
        window.location.href = api.getLoginUrl();
      },

      logout: () => {
        set({ token: null, userProfile: null });
        window.location.href = "/login";
      },

      fetchUserProfile: async () => {
        const { token } = get();
        if (!token) return;
        try {
          const profile = await api.getCurrentUser(token);
          set({ userProfile: profile });
        } catch (error) {
          console.error("Failed to fetch user profile:", error);
          // If token is invalid, clear it
          set({ token: null, userProfile: null });
        }
      },
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({ token: state.token }),
      onRehydrateStorage: () => {
        return (state) => {
          state?.setHydrated(true);
          // Fetch user profile after hydration if token exists
          if (state?.token) {
            state.setLoading(true);
            state.fetchUserProfile().finally(() => {
              state.setLoading(false);
            });
          }
        };
      },
    }
  )
);
