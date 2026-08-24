import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
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
   * keep the old value until a reload.
   *
   * Ignored unless the update still describes the session that is signed in:
   * a PATCH in flight when the user signs out would otherwise resolve after
   * `signOut` cleared the state and put the old identity back — tokens gone,
   * `user` non-null, so every role gate reads as signed in. An id check alone
   * misses the narrower case of signing back into the *same* account before
   * the old PATCH resolves — same id, wrong session — so callers additionally
   * pass the `epoch` they read from `useApplyUser()` at the moment they fired
   * the request; `applyUser` drops anything whose epoch does not match the
   * one signIn/signOut most recently bumped. */
  applyUser: (user: User, epoch: number) => void;
  /** Bumped by every `signIn`/`signOut`. Read at render time — a component
   * that (re)mounts after a sign-out/sign-in cycle sees the new value the
   * next time it calls `useApplyUser()`, which is what lets that hook bind
   * each caller's write to the session it was fired under. */
  epoch: number;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  // A ref, not state: it only needs to be current when signIn/signOut's own
  // setUser call forces the re-render that reads it, never on its own.
  const epochRef = useRef(0);

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
    epochRef.current += 1;
    storeTokens(auth.tokens);
    setUser(auth.user);
  }, []);

  const signOut = useCallback(() => {
    epochRef.current += 1;
    logout().catch(() => {
      // best-effort: cookie may already be gone
    });
    storeTokens(null);
    setUser(null);
  }, []);

  // Functional update, matched on id and epoch: the decision has to be made
  // against the state at the moment it applies, not the state captured when
  // the write started. A signed-out provider (`current` null) and a
  // different signed-in user both mean this response belongs to a session
  // that is over — but so does a *matching* id whose epoch has moved on,
  // which is what catches signing back into the same account before an
  // earlier write resolves (id-only can't tell those two sessions apart).
  const applyUser = useCallback((updated: User, epoch: number) => {
    if (epoch !== epochRef.current) return;
    setUser((current) => (current?.id === updated.id ? updated : current));
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, loading, signIn, signOut, applyUser, epoch: epochRef.current }}
    >
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
 * not exist to update" rather than crashing the screen it sits on.
 *
 * Binds the returned function to the epoch current *at this render*. A
 * `useMutation`'s `onSuccess` closes over whatever this hook returned when
 * the component last rendered before `.mutate()` was called — TanStack Query
 * keeps calling that same closure if the promise resolves after the owning
 * component has unmounted (verified: it does not get skipped or rebound to a
 * later render), which is exactly the sign-out/sign-back-in-as-the-same-user
 * window this exists to close. A component that is still mounted re-renders
 * on every `signIn`/`signOut` (context value changes), so a live caller
 * always has the current epoch by the time it fires its next request. */
export function useApplyUser(): (user: User) => void {
  const ctx = useContext(AuthContext);
  const epoch = ctx?.epoch ?? 0;
  return useCallback((user: User) => ctx?.applyUser(user, epoch), [ctx, epoch]);
}
