import { useEffect, useState } from "react";
import { fetchFileUrl } from "../api/homework";

/** Renders a protected image inline, or a protected PDF via an open-in-tab link. */
export function AuthImage({ path, alt }: { path: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoked: string | null = null;
    fetchFileUrl(path)
      .then((u) => {
        revoked = u;
        setUrl(u);
      })
      .catch(() => setFailed(true));
    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [path]);

  if (failed) return <p className="text-sm text-red-600">Could not load {alt}.</p>;
  if (!url) return <div className="h-40 animate-pulse rounded bg-slate-100" />;
  return <img src={url} alt={alt} className="w-full rounded border" />;
}

export function AuthFileLink({ path, label }: { path: string; label: string }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <button
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        setFailed(false);
        try {
          const url = await fetchFileUrl(path);
          window.open(url, "_blank");
        } catch {
          // Since task 1.2, tutor material can redirect to the object store —
          // a network failure or bucket CORS misconfiguration surfaces here
          // as a rejected fetch rather than a response status to check.
          setFailed(true);
        } finally {
          setBusy(false);
        }
      }}
      className="text-blue-600 hover:underline disabled:opacity-50"
    >
      {busy ? "Opening…" : failed ? "Couldn't open — try again" : label}
    </button>
  );
}
