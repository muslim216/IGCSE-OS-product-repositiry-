import { useEffect, useState } from "react";
import { fetchFileUrl } from "../api/homework";
import { Skeleton } from "./page";

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

  if (failed) {
    return (
      <p className="rounded-md border border-line bg-surface-muted px-3 py-6 text-center text-sm text-ink-500">
        Couldn&apos;t load {alt}. Refresh the page to try again.
      </p>
    );
  }
  if (!url) return <Skeleton className="h-40 w-full" />;
  return <img src={url} alt={alt} className="w-full rounded-md border border-line" />;
}

export function AuthFileLink({ path, label }: { path: string; label: string }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <button
      // Explicit, so it can never submit a form it happens to be placed in —
      // a bare <button> defaults to type="submit".
      type="button"
      disabled={busy}
      aria-busy={busy || undefined}
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
      className={`font-medium transition-colors disabled:opacity-50 ${
        failed ? "text-risk-600 hover:opacity-80" : "text-brand-600 hover:text-brand-700"
      }`}
    >
      {busy ? "Opening…" : failed ? "Couldn't open — try again" : label}
    </button>
  );
}
