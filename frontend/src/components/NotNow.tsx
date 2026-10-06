import { Button } from "./controls";
import type { Dismissals } from "../lib/dismissals";

/** The page's one live region for hides, and the place a failed hide is said.
 *  Always mounted by the page, never by the section it describes: a section whose
 *  last item was hidden renders nothing, and its announcement must outlive it.
 *  Focusable so focus has somewhere to land when the thing it was on is gone. */
export function DismissalStatus({ dismissals }: { dismissals: Dismissals }) {
  return (
    <>
      <p role="status" tabIndex={-1} data-dismissal-status className="sr-only focus:outline-none">
        {dismissals.notice}
      </p>
      {dismissals.error && (
        <p role="alert" className="text-sm text-risk-600">
          {dismissals.error}
        </p>
      )}
    </>
  );
}

function focusStatus() {
  document.querySelector<HTMLElement>("[data-dismissal-status]")?.focus();
}

/** "Not now": hides one thing for good, until the tutor brings it back from the
 *  bottom of the page. `what` names it for the accessible name, so a screen
 *  reader's button list says which one. Focus moves to the next "Not now" in the
 *  same list (else the one before, else the status line) before the hidden row
 *  goes, so it never falls to the top of the page. */
export default function NotNow({
  what,
  dismissals,
  hideKey,
  scope = false,
}: {
  what: string;
  dismissals: Dismissals;
  /** What is stored. Null means this thing has nothing to be stored under yet,
      and then there is no button: one that announced "Hidden" and hid nothing
      would be worse than none. */
  hideKey: string | null;
  /** True for the whole guide, which has no neighbours to hand focus to. */
  scope?: boolean;
}) {
  if (hideKey === null) return null;
  return (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      data-not-now
      aria-label={`Not now: ${what}`}
      onClick={(e) => {
        const here = e.currentTarget;
        let target: HTMLElement | null = null;
        if (!scope) {
          const list = here.closest("[data-not-now-scope], section");
          const all = Array.from(list?.querySelectorAll<HTMLElement>("[data-not-now]") ?? []);
          const i = all.indexOf(here);
          target = all[i + 1] ?? all[i - 1] ?? null;
        }
        (target ?? undefined)?.focus();
        if (!target) focusStatus();
        dismissals.hide(hideKey, what);
      }}
    >
      Not now
    </Button>
  );
}

/** The quiet line at the bottom of Overview. Nothing when nothing is hidden. */
export function HiddenFooter({ dismissals }: { dismissals: Dismissals }) {
  if (dismissals.hiddenCount <= 0) return null;
  return (
    <p className="mt-8 flex items-center gap-2 text-sm text-ink-500">
      {dismissals.hiddenCount} hidden
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={() => {
          focusStatus();
          dismissals.restoreAll();
        }}
      >
        Show hidden
      </Button>
    </p>
  );
}
