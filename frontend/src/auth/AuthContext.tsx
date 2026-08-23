import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { getStoredTokens, storeTokens, type AuthResponse, type User } from "../api/client";
import { fetchMe, logout } from "../api/auth";

interface AuthState {
  user: User | null;
  loading: boolean;
  signIn: (auth: AuthResponse) => void;
  signOut: () => void;
  /** Replace the cached identity after the server returns an updated one.
   *
   * The provider loads the user once, with `fetchMe()` on mount, so anything
   * that changes a field on that row has to say so — invalidating a TanStack
   * query does not reach this state. Without it a user can save a preference,
   * see the control confirm it, and watch every screen that reads the identity
   * keep the old value until a reload. */
  applyUser: (user: User) => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getStoredTokens()) {
      setLoading(false);
      return;
    }
    fetchMe()
      .then(setUser)
      .catch(() => storeTokens(null))
      .finally(() => setLoading(false));
  }, []);

  const signIn = useCallback((auth: AuthResponse) => {
    storeTokens(auth.tokens);
    setUser(auth.user);
  }, []);

  const signOut = useCallback(() => {
    logout().catch(() => {
      // best-effort: cookie may already be gone
    });
    storeTokens(null);
    setUser(null);
  }, []);

  const applyUser = useCallback((updated: User) => setUser(updated), []);

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut, applyUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** The signed-in user's own zone (AV-67), or null when there is none.
 *
 * Deliberately does NOT throw outside the provider, where `useAuth` does. That
 * strictness exists so nothing mistakes "no provider" for "signed out" while
 * deciding what a user may see; this reads one presentation preference, and
 * null already means "use the browser's zone" everywhere it is consumed. A
 * date label is not an authorization decision and must not be able to blank a
 * screen. */
export function useMyTimezone(): string | null {
  return useContext(AuthContext)?.user?.time_zone ?? null;
}

/** Update the cached identity, or do nothing outside a provider.
 *
 * Non-throwing for the same reason as `useMyTimezone`: a settings control that
 * renders in isolation should degrade to "the write happened, this cache did
 * not exist to update" rather than crashing the screen it sits on. */
export function useApplyUser(): (user: User) => void {
  const ctx = useContext(AuthContext);
  return ctx?.applyUser ?? (() => {});
}
