# Avora — Visual Identity

**Type:** Design document (Tier 2). **Status:** Active. **Owner:** Founder.

> This document defines Avora's **visual identity only**. It does not replace, modify, or
> override `docs/experience-design.md` or `docs/experience-implementation-plan.md`, which remain
> authoritative for information architecture, navigation, page structure, functionality, states,
> copy, hierarchy, interaction, responsive behaviour, and accessibility. Its job is to apply the
> Avora visual language — parchment, espresso, terracotta, Lora, Inter, editorial typography,
> restrained asymmetry, subtle texture, the Avora mark, generous whitespace, warm borders, calm
> motion — to the existing product. **When visual ambition conflicts with a UX or accessibility
> requirement, the requirement wins and the visual treatment adapts.**

## Where this sits

This is **Phase 2** as defined by `experience-design.md` §11 ("visual language, typography,
motion"). Phase 1 — the settled IA — is not this document's to change. The binding rules of the
design system live in `docs/volume-1-product-and-ux/02-ux-and-accessibility-standards.md` (`UX-*`);
this document cites them, it does not restate them (`GOV-5`). The tokens themselves live in
`frontend/src/index.css`; §02's colour and typography tables are the maintained mirror.

## The feeling

Intelligent, warm, calm, considered. Editorial, not corporate; warm, not childish; confident,
not flashy. The guiding sentence: **not impressive, not flashy — just obvious clarity.**

## Colour

The palette is the Avora light identity. Full token values, roles, and measured contrast are in
§02; the identity intent is summarised here.

- **Parchment** `#FAF7F2` is the dominant canvas; **cream** `#FDF9F4` lifts cards a step
  ("paper on paper"), **linen** `#F0EBE1` a step further for muted rows. The steps are subtle by
  design — no competing white panels.
- **Espresso** `#2C1A0E` is primary text and the colour of the dark interlude sections; **bark**
  and **driftwood** are the two quieter text steps.
- **Terracotta** is the single accent, used sparingly — it is special *because* it is restrained.
  The functional accent token (`brand-600` `#a85033`) is deepened from the identity's display
  terracotta `#B86040` so it can carry a button label and accent text at 4.5:1; the pure
  `#B86040` is reserved for large decorative use (the mark, the display wordmark) where WCAG sets
  no ratio. **Sienna** `#D4956A` is the soft/hover accent, decorative only.
- **Status colours are functional, state only, never decoration** (`UX-4`, `UX-15`). Their hues
  are held clearly apart from terracotta (green 146°, amber 36°, red 3°, purple 261° vs the
  accent's ≈15°) so the brand colour is never read as a warning. The status labels — **On track /
  Needs attention / At risk** — are a Tier-1 union and are **not** renamed here.

## Typography

**Lora** is the display/editorial voice (headings, the wordmark, pull quotes); **Inter** is the
functional UI voice (body, labels, controls, tables). Both are **self-hosted** via
`@fontsource-variable/*`, imported in `main.tsx`, and bundled by Vite as same-origin assets, so
the CSP's `font-src 'self'` is met with no external host — the security posture is unchanged.
Small tracked uppercase labels (`.avora-label`) are part of the editorial language; the
occasional serif-italic emphasis uses Lora's italic axis.

## The mark and motifs

Reusable graphics live in `frontend/src/components/brand.tsx`. All are decorative:
`aria-hidden`, non-interactive, and coloured from a token via `currentColor`, so they never touch
the accessibility tree or the contrast budget (`UX-14`).

- **`AvoraMark`** — the mark, used from micro ornament to ghost scale. **This is a placeholder**
  (an "aperture" arch) until the approved artwork is supplied; `brand.tsx` and
  `public/favicon.svg` are each a one-edit swap.
- **`AvoraWordmark` / `AvoraLockup`** — the display "avora" (Lora) for brand moments, and the
  compact mark-plus-name lockup for chrome. The wordmark is **avora**, alone — no sub-line.
- **`GhostMark`** — a large, faint mark as background mass; never over text, never interactive,
  hidden on small screens.
- **`SectionOrnament`, `EspressoSection`, `AvoraGrain`** — a mark-between-rules divider, a
  dark espresso interlude with a subtle dot-grid, and a barely-visible fixed paper-grain overlay.

## Surfaces, depth, motion

Cards are editorial and quiet: cream fills, warm `line` borders, a whisper of warm shadow, no
glow (`UX-5`). The dark espresso section is a contrast-rhythm device, not a theme — the product
is one light theme. Motion is calm CSS transitions and respects `prefers-reduced-motion`
(`UX-17`).

## The boundary, restated

The identity presentation is an *expression* of the brand; the product does not copy its layout.
The product receives the colours, typography, texture, composition language, and motifs — not the
identity page's content structure. Applying the identity must not move a section, change copy,
alter a state, or add or remove a feature. Asymmetry and whitespace are welcome only where they
leave the established hierarchy and information density intact.

## What is deliberately deferred

- The **real mark artwork** (placeholder until supplied).
- The **docs-wide `MANARA` → `avora` prose rename** — only the visible product and the two
  governance documents that a token change obliges (`§02`, this file, `README.md`) are changed
  here.
- **Bespoke per-surface editorial redesign** of the Tutor/Student/Parent surfaces — that is the
  IA-touching work of implementation-plan Stages 5–7, out of scope for a visual pass. Those
  surfaces inherit the Avora palette and type automatically through the `index.css` retarget.
