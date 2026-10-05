import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { latestWeeklySend } from "../api/weeklySend";
import { weekLabel, weeklySendPath, type ShellHome } from "../lib/weeklySend";

/**
 * "This week's send is out" on a home page (AV-51, task 8.4).
 *
 * A link into the stored send, not a copy of it: the send is a scheduled
 * artifact and the home page's own paragraph is always current, so folding one
 * into the other would let them drift.
 *
 * Renders nothing while loading, on error, and before a first send exists. It
 * is one line on a page that has its own primary content; a spinner or an
 * error block for it would compete with that content for no gain.
 *
 * `home` is the shell the page lives in. Each home page knows its own, so this
 * needs no identity lookup of its own.
 */
export default function WeeklySendLink({ home }: { home: ShellHome }) {
  const latest = useQuery({ queryKey: ["weekly-send", "latest"], queryFn: latestWeeklySend });
  const send = latest.data;
  // `id` checked, not just truthiness: anything that is not a send renders nothing.
  if (!send || typeof send.id !== "number") return null;
  return (
    <p className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-xl border border-line bg-surface px-5 py-3 text-sm">
      <span className="text-ink-700">
        This week&apos;s send is out{" "}
        <span className="text-ink-500">· {weekLabel(send.week_start, send.week_end)}</span>
      </span>
      <Link to={weeklySendPath(home, send.id)} className="font-medium text-brand-600">
        Read it <span aria-hidden>→</span>
      </Link>
    </p>
  );
}
