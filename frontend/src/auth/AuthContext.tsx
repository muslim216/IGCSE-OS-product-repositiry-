import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { getStoredTokens, storeTokens, type AuthResponse, type User } from "../api/client";
import { fetchMe, logout } from "../api/auth";

interface AuthState {
  user: User | null;
  loading: boolean;
  signIn: (auth: AuthResponse) => void;
  signOut: () => void;
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

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut }}>
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
