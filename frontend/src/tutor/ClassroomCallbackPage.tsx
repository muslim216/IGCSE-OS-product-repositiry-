import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { connectClassroom } from "../api/classroom";
import { ApiError } from "../api/client";
import { OAUTH_STATE_KEY } from "./ClassroomSettingsPage";

/** Where Google sends the tutor back after they approve access. Verifies the
 * `state` we stashed before leaving, exchanges the code, and returns to
 * Settings. Lives outside the AppShell — it's a redirect target, not a page
 * anyone navigates to. */
export default function ClassroomCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  // React 18 StrictMode mounts effects twice in dev; the code is single-use.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const code = params.get("code");
    const state = params.get("state");
    const expected = sessionStorage.getItem(OAUTH_STATE_KEY);
    sessionStorage.removeItem(OAUTH_STATE_KEY);

    if (params.get("error")) {
      setError("Google didn't grant access. Nothing was connected.");
      return;
    }
    if (!code || !state) {
      setError("That link is missing information from Google. Try connecting again.");
      return;
    }
    if (!expected || state !== expected) {
      setError(
        "This sign-in didn't start from this browser, so it was rejected. Try connecting again.",
      );
      return;
    }

    connectClassroom(code, state)
      .then(() => navigate("/tutor/settings", { replace: true }))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : String(err)),
      );
  }, [params, navigate]);

  return (
    <div className="mx-auto max-w-md p-8">
      {error ? (
        <>
          <p className="text-sm text-red-600">{error}</p>
          <button
            onClick={() => navigate("/tutor/settings", { replace: true })}
            className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
          >
            Back to settings
          </button>
        </>
      ) : (
        <p className="text-slate-500">Connecting your Google Classroom account…</p>
      )}
    </div>
  );
}
