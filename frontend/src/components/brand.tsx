import type { ReactNode } from "react";

/* Avora brand motifs. Reusable, decorative, and — except where a wordmark
   carries the product name as real text — non-interactive and aria-hidden, so
   they add art direction without touching the accessibility tree (UX-14). Every
   graphic inherits `currentColor`, so a caller sets the colour with a token
   class (`text-brand-600`, `text-ink-900`) rather than a hex (UX-3). */

/* ---------------------------------------------------------------------------
   PLACEHOLDER MARK.

   The approved Avora mark artwork is supplied separately. Until it lands, this
   is a deliberate placeholder: a warm arch — an "aperture" evoking "avora" —
   drawn in `currentColor` so it recolours with the surrounding text. It is NOT
   the official mark. Replacing it is a one-component swap: drop the real SVG
   paths into `AvoraMark` (and `public/favicon.svg`) and nothing else changes,
   because every scale below composes this single component.
   --------------------------------------------------------------------------- */
export function AvoraMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={`${className} shrink-0`}>
      {/* an arch over a level base — a doorway/aperture motif */}
      <path
        d="M4 20 V13 a8 8 0 0 1 16 0 V20"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path d="M4 20 H20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* The display wordmark — "avora" set in Lora, behaving like typography rather
   than a logo. Used at brand moments (hero, sign-in, empty states), not on every
   screen. Sizing is responsive via clamp; the caller sets the colour. */
export function AvoraWordmark({ className = "" }: { className?: string }) {
  return (
    <span
      className={`font-display lowercase leading-none tracking-[-0.03em] ${className}`}
      style={{ fontSize: "clamp(2.5rem, 7vw, 6rem)" }}
    >
      avora
    </span>
  );
}

/* The compact lockup used in navigation and page chrome: the mark beside the
   "avora" name. This is the everyday wordmark, distinct from the large display
   treatment above. */
export function AvoraLockup({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <AvoraMark className="h-8 w-8 shrink-0 text-brand-600" />
      <span className="font-display text-2xl lowercase tracking-[-0.01em] text-ink-900">avora</span>
    </div>
  );
}

/* The ghost mark — a very large, faint mark that behaves as background mass
   behind content. It must never obscure text, reduce contrast, or intercept a
   click, so it is aria-hidden, pointer-events-none, and pinned behind content.
   On small screens it is hidden entirely rather than allowed to compete. */
export function GhostMark({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute hidden select-none text-brand-500 md:block ${className}`}
      style={{ width: "clamp(320px, 42vw, 600px)", opacity: 0.06 }}
    >
      <AvoraMark className="h-full w-full" />
    </div>
  );
}

/* A tiny mark used as a section ornament between two thin rules (§23). */
export function SectionOrnament({ className = "" }: { className?: string }) {
  return (
    <div aria-hidden className={`flex items-center gap-3 text-line-strong ${className}`}>
      <span className="h-px flex-1 bg-line" />
      <AvoraMark className="h-3 w-3 text-brand-500" />
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

/* A full-width espresso interlude with the subtle dot-grid (§18–20). A
   contrast-rhythm device: a quiet change of atmosphere, not a dark theme. */
export function EspressoSection({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`avora-espresso ${className}`}>{children}</section>;
}

/* The paper grain overlay — mounted once per top-level layout. An inline SVG
   turbulence filter (not an external asset), fixed above content only to tint
   it. Barely visible by design; positioning and blend live in `.avora-grain`. */
export function AvoraGrain() {
  return (
    <svg aria-hidden className="avora-grain" xmlns="http://www.w3.org/2000/svg">
      <filter id="avora-grain-filter">
        <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" stitchTiles="stitch" />
      </filter>
      <rect width="100%" height="100%" filter="url(#avora-grain-filter)" />
    </svg>
  );
}
