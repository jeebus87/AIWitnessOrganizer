import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  auth,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
  signInWithPopup,
  googleProvider,
} from "@/lib/firebase";
import type { User } from "@/lib/firebase";
import { api } from "@/lib/api";
import type { UserProfile } from "@/lib/api";

interface AuthState {
  user: User | null;
  userProfile: UserProfile | null;
  token: string | null;
  isLoading: boolean;
  isHydrated: boolean;
  error: string | null;
  setUser: (user: User | null) => void;
  setUserProfile: (profile: UserProfile | null) => void;
  setToken: (token: string | null) => void;
  setError: (error: string | null) => void;
  setHydrated: (hydrated: boolean) => void;
  loginWithEmail: (email: string, password: string) => Promise<void>;
  loginWithGoogle: () => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<string | null>;
  fetchUserProfile: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      userProfile: null,
      token: null,
      isLoading: true,
      isHydrated: false,
      error: null,

      setUser: (user) => set({ user }),
      setUserProfile: (profile) => set({ userProfile: profile }),
      setToken: (token) => set({ token }),
      setError: (error) => set({ error }),
      setHydrated: (hydrated) => set({ isHydrated: hydrated }),

      loginWithEmail: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const userCredential = await signInWithEmailAndPassword(auth, email, password);
          const token = await userCredential.user.getIdToken();
          set({ user: userCredential.user, token, isLoading: false });
          await get().fetchUserProfile();
        } catch (error: unknown) {
          const message = error instanceof Error ? error.message : "Login failed";
          set({ error: message, isLoading: false });
          throw error;
        }
      },

      loginWithGoogle: async () => {
        set({ isLoading: true, error: null });
        try {
          const userCredential = await signInWithPopup(auth, googleProvider);
          const token = await userCredential.user.getIdToken();
          set({ user: userCredential.user, token, isLoading: false });
          await get().fetchUserProfile();
        } catch (error: unknown) {
          const message = error instanceof Error ? error.message : "Google login failed";
          set({ error: message, isLoading: false });
          throw error;
        }
      },

      register: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const userCredential = await createUserWithEmailAndPassword(auth, email, password);
          const token = await userCredential.user.getIdToken();
          set({ user: userCredential.user, token, isLoading: false });
        } catch (error: unknown) {
          const message = error instanceof Error ? error.message : "Registration failed";
          set({ error: message, isLoading: false });
          throw error;
        }
      },

      logout: async () => {
        await signOut(auth);
        set({ user: null, token: null, userProfile: null });
      },

      refreshToken: async () => {
        const { user } = get();
        if (!user) return null;
        try {
          const token = await user.getIdToken(true);
          set({ token });
          return token;
        } catch {
          return null;
        }
      },

      fetchUserProfile: async () => {
        const { token } = get();
        if (!token) return;
        try {
          const profile = await api.getCurrentUser(token);
          set({ userProfile: profile });
        } catch (error) {
          console.error("Failed to fetch user profile:", error);
        }
      },
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({ token: state.token }),
      onRehydrateStorage: (state) => {
        return () => {
          state?.setHydrated(true);
        };
      },
    }
  )
);

// Initialize auth listener
if (typeof window !== "undefined") {
  onAuthStateChanged(auth, async (user) => {
    if (user) {
      const token = await user.getIdToken();
      useAuthStore.setState({ user, token, isLoading: false });
    } else {
      useAuthStore.setState({ user: null, token: null, isLoading: false });
    }
  });
}
