import { useEffect, useState } from "react";

/* The JavaScript half of the motion system. The values themselves live in
   index.css; this file only exists because CSS cannot keep an element in the
   DOM while it animates out. */

/** How long an exit animation runs. Mirrors `--dur-exit` in index.css — change
    the two together, or an element is removed before (or held after) its
    animation ends. */
export const EXIT_MS = 140;

/**
 * Whether this device has affirmatively said motion is fine. Asked as
 * `no-preference` rather than "not reduce" so that anything unable to answer —
 * a browser without matchMedia, the jsdom the tests run in — is treated as
 * reduced: content is removed at once instead of waiting on an animation that
 * will never play.
 */
export function motionAllowed(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: no-preference)").matches;
}

/**
 * Keeps something rendered for `EXIT_MS` after `open` turns false, so its exit
 * animation can play. `closing` is true for that window. Under reduced motion
 * there is no window: `mounted` follows `open` in the same render.
 */
export function usePresence(open: boolean): { mounted: boolean; closing: boolean } {
  const [mounted, setMounted] = useState(open);
  const [wasOpen, setWasOpen] = useState(open);
  // Adjusted during render, not in an effect: an effect would commit one frame
  // of "closed and gone" before reopening, and one frame of "still here" before
  // closing under reduced motion.
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setMounted(true);
    else if (!motionAllowed()) setMounted(false);
  }
  const closing = mounted && !open;

  useEffect(() => {
    if (!closing) return;
    const timer = setTimeout(() => setMounted(false), EXIT_MS);
    return () => clearTimeout(timer);
  }, [closing]);

  return { mounted, closing };
}
