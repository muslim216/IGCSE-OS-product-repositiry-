# 02. UX & Accessibility Standards

> **Volume 1 — Product & UX** · Engineering Constitution v1.2 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> Governs the MANARA design system, interaction patterns, and the accessibility standard the
> product is held to.

## Contents

- [Purpose](#purpose)
- [Scope](#scope)
- [Sources](#sources)
- [Principles](#principles)
- [Current Reality](#current-reality)
  - [The design system lives in one CSS file](#the-design-system-lives-in-one-css-file)
  - [Colour tokens](#colour-tokens)
  - [The Tailwind retarget layer](#the-tailwind-retarget-layer)
  - [Typography](#typography)
  - [Component primitives](#component-primitives)
  - [Measured contrast](#measured-contrast)
  - [Accessibility as practiced](#accessibility-as-practiced)
- [Standards](#standards)
- [Known Gaps](#known-gaps)
- [Review Triggers](#review-triggers)

---

## Purpose

Until this document, the MANARA design system existed only as 283 lines of CSS that nobody
had described, and accessibility was a set of habits applied unevenly across 60-odd
components. Both are load-bearing: the CSS contains a mechanism that will surprise anyone who
edits it naively, and the product is used by children.

This document describes the visual system as it is, sets the accessibility standard the
product is held to, and defines the interaction patterns that carry §01's data principles
into the interface.

## Scope

**In scope:** design tokens and their meaning; the Tailwind retargeting mechanism;
typography; the shared component primitives in `components/ui.tsx`; contrast requirements;
keyboard, focus, and screen-reader requirements; loading, empty and error patterns; the
display contract for absent and self-declared data; role-specific interface obligations.

**Out of scope:** React implementation patterns, routing, and data fetching (§03); the API
that feeds the interface (§05); the CSP that constrains font loading (§07, §08).

### Non-goals

- **A single theme, not both.** The palette is the **Avora** light identity —
  `:root { color-scheme: light }`, a warm parchment canvas — and it is the only theme. There is
  no dark mode and no theme toggle; supporting both would double every contrast decision. *(This
  supersedes the earlier "No light mode" non-goal: the product was a dark midnight theme until
  the Avora rebrand inverted it to light. See `docs/avora-visual-identity.md`.)*
- **No component library.** No Radix, no shadcn, no Headless UI. Primitives are hand-rolled
  in `components/ui.tsx`. This is a deliberate cost: the project owns its accessibility
  behaviour rather than inheriting it, which is why the `Modal` gaps below are ours to fix.
- **Webfonts are self-hosted, never fetched from a CDN.** The identity uses **Lora** (display)
  and **Inter** (functional), shipped via `@fontsource-variable/*` and bundled by Vite as
  same-origin assets, so the CSP's `font-src 'self'` is satisfied with no external host. The
  security constraint is unchanged; the fonts live inside the origin rather than being given up.
  *(This supersedes the earlier "No webfonts" non-goal, which assumed a CDN was the only way to
  load one.)*
- **No second accent colour.** Terracotta is the product's only accent. Status colours are
  semantic, not decorative, and are held apart in hue from the accent so the brand colour never
  reads as a warning.
- **No animation library.** Motion is CSS transitions where it clarifies a state change, and it
  respects `prefers-reduced-motion` (`UX-17`).

## Sources

Written from: `frontend/src/index.css` (306 lines); `frontend/src/components/ui.tsx`;
`frontend/src/components/AppShell.tsx`; `frontend/src/App.tsx`; `frontend/index.html`;
`frontend/vercel.json`; and a repository-wide audit of ARIA attribute and semantic element
usage across `frontend/src/**/*.tsx`. Contrast figures are computed from the token values in
`index.css` using the WCAG 2.x relative-luminance formula.

---

## Principles

**P1 — The interface never invents a number.** §01 P3 is a data principle; here it is a
rendering contract. A missing measurement is shown as missing, in words, never as `0`, `0%`,
or an empty bar that reads as zero.

**P2 — Say where a number came from.** Scores carry their confidence, their evidence count,
or a route to their inputs. A figure a tutor cannot interrogate is one they cannot defend to
a parent.

**P3 — Calm over urgent.** The palette is deliberately quiet: one accent, muted status
colours, depth from surface lift rather than glow. This product tells children how ready they
are for exams. It should not shout.

**P4 — Accessible by construction, not by audit.** Semantic elements, labelled controls, and
visible focus are the default state of new work, not a pass made later. Retrofitting
accessibility across 60 components is the situation this document exists to prevent
recurring.

**P5 — The interface is honest about what the platform knows.** Self-declared data is labelled
self-declared. AI-produced values are labelled as proposals until accepted. "Updating" is
shown over a stale score rather than presenting it as current.

---

## Current Reality

### The design system lives in one CSS file

`frontend/src/index.css` is the entire design system. There is **no `tailwind.config.js` and
no `postcss.config.js`** — Tailwind v4 is configured CSS-first via the `@tailwindcss/vite`
plugin and `@import "tailwindcss"`.

The file has two halves, and they behave very differently:

1. **The `@theme` block at the top.** Design tokens as CSS custom properties. Tailwind
   generates utility classes from these: `bg-canvas`, `text-ink-500`, `border-line`,
   `bg-brand-600`, `font-display`.
2. **The rest of the file, the retarget layer.** Unlayered CSS that redefines Tailwind's *stock*
   palette utilities — `.bg-white`, `.text-slate-500`, `.bg-blue-600` — to point at MANARA
   tokens.

### Colour tokens

The **Avora** palette. The retained token *names* are semantic and unchanged from the previous
(dark) theme — only their values moved — so the retarget layer and every component keep working.
(The full name set is unchanged: `remark-*` and `line-control` already existed in the dark theme,
and `ink-400` was already removed before this change; the rebrand re-valued names, it did not add
or drop any.)

| Group | Token | Value | Role |
|---|---|---|---|
| Surfaces | `--color-canvas` | `#faf7f2` | "Parchment" — body canvas |
| | `--color-surface` | `#fdf9f4` | "Cream" — cards, panels, modals |
| | `--color-surface-muted` | `#f0ebe1` | "Linen" — raised rows, hovers, skeletons |
| Text | `--color-ink-900` | `#2c1a0e` | "Espresso" — headings, primary text |
| | `--color-ink-700` | `#4a3527` | "Bark" — body copy |
| | `--color-ink-500` | `#786351` | "Driftwood" — labels, captions, nav (the dimmest token that may carry normal text) |
| Accent | `--color-brand-700/600/500` | `#96452a` / `#a85033` / `#d4956a` | "Terracotta / Sienna" — the product's only accent. `600` is the functional fill/accent-text value; `500` (sienna) is soft/decorative only |
| | `--color-brand-100/50` | terracotta at 14% / 7% | Accent tints |
| Status | `--color-ok-700` / `ok-100` | `#22593a` / `rgba(42,107,70,.14)` | On track (green, 146°) |
| | `--color-warn-700` / `warn-100` | `#744c0e` / `rgba(138,90,22,.14)` | Needs attention (amber, 36°) |
| | `--color-risk-600` / `risk-100` | `#992d27` / `rgba(176,52,46,.14)` | At risk (red, 3°) |
| | `--color-remark-600` / `remark-100` | `#5c438c` / `rgba(107,78,155,.14)` | Remark requests (purple, 261°) — semantic request colour, its own family, not a reuse of warn and not an accent |
| Hairlines | `--color-line` | `#e2d9cc` | "Warm-stone" — decorative borders and dividers |
| | `--color-line-strong` | `#cbbca8` | Emphasised dividers, scrollbar thumb |
| | `--color-line-control` | `#8c7a66` | The boundary of an interactive control — inputs, selects, textareas. The only one of the three that meets WCAG 1.4.11 |

`--color-gold-600/500/100` are aliases of the terracotta ramp, kept so older class names stay
valid. They are not a separate colour. Status hues are deliberately separated from the
terracotta accent (≈15°) so the brand colour never reads as a warning (`UX-4`); the identity's
display terracotta `#B86040` is reserved for large decorative brand use (the mark, the display
wordmark), because as a mid-tone it cannot carry normal text at 4.5:1 in either direction —
which is why the functional `brand-600` is deepened to `#a85033`.

### The Tailwind retarget layer

**This is the mechanism that will surprise you.** Roughly 240 lines redefine Tailwind's stock
utilities:

```css
.bg-white       { background-color: var(--color-surface); color: var(--color-ink-700); }
.text-slate-500 { color: var(--color-ink-500); }
.bg-blue-600    { background-color: var(--color-brand-600); color: var(--color-canvas); }
.bg-green-100   { background-color: var(--color-ok-100); }
```

Because the theme inverted from dark to light, one retarget case changed behaviour rather than
just colour: the dark-chip buttons written as `.bg-slate-700` + `.text-white` would have gone
white-on-white on parchment, so `.bg-slate-700/800` now map to **espresso** with cream text —
the same "dark, quiet, secondary" intent, inverted correctly.

The comment above that block explains why it works: **unlayered rules always win over
Tailwind's own `@layer utilities` in the cascade**, so this re-themes every generated class
app-wide without `!important` and without editing every page.

Three consequences a new engineer must know:

- **`bg-white` is not white.** It is `--color-surface`, and it also sets a text colour. Nine
  other stock names are similarly redirected.
- **The codebase carries two parallel class vocabularies.** Newer code uses semantic tokens
  (`bg-surface`, `text-ink-700`, `border-line`); older code uses `bg-white`,
  `text-slate-600`, `bg-blue-600`, silently remapped. Both render correctly. Only one is
  self-describing.
- **The block must stay unlayered.** Wrapping it in `@layer` would lose the cascade fight and
  revert the entire application to stock Tailwind colours.

The layer also styles bare elements, which is why legacy inputs render correctly: `input,
select, textarea` get `--color-surface` (cream) background, `--color-ink-900` text, and
`--color-line-control` borders; placeholders get `--color-ink-500`.

### Typography

`--font-display` is `"Lora Variable", …, serif` and `--font-sans` is `"Inter Variable", …,
sans-serif`. **Lora** carries the editorial/display voice and **Inter** the functional UI. Both
are **self-hosted** — imported through `@fontsource-variable/*` in `main.tsx` and bundled by
Vite as same-origin `dist/assets/*.woff2`, so `frontend/vercel.json`'s `font-src 'self'` is
satisfied with no external host. Each token keeps a system fallback stack in case an asset fails
to load. *(Earlier revisions used a system serif because a CDN was assumed to be the only source
for a webfont; self-hosting removes that assumption without loosening the CSP.)*

`h1` and `h2` use Lora with `letter-spacing: -0.01em` and `--color-ink-900`. `h3` stays sans —
dense interface areas keep their clarity that way. Everything below is Inter. Inside an
`.avora-espresso` section, headings flip to cream via a more-specific unlayered rule, since the
global `h1, h2 { color: ink-900 }` would otherwise render espresso-on-espresso.

### Brand motifs

`frontend/src/components/brand.tsx` holds the reusable Avora graphics — the mark, the display
wordmark, the compact lockup, a faint ghost mark, a section ornament, an espresso interlude, and
a fixed paper-grain overlay. Every one is decorative: `aria-hidden`, non-interactive, and
colour-set from a token via `currentColor`, so none of them touch the accessibility tree or the
contrast budget. The grain and ghost mark reduce or disappear on small screens rather than
compete with content. **The mark in `brand.tsx` and `public/favicon.svg` is a placeholder** until
the approved artwork is supplied; both are isolated so the swap is one edit each.

### Component primitives

`frontend/src/components/ui.tsx` is the house vocabulary. Nothing is imported from a
component library.

| Primitive | Behaviour worth knowing |
|---|---|
| `initials()` / `InitialsAvatar` | Avatar is `aria-hidden`; the name is always rendered nearby |
| `SectionHeader` | Uppercase tracked label in `brand-600`, optional description and action |
| `SectionCard` | `rounded-xl border border-line bg-surface p-5` with a 1px shadow — depth from surface lift, not glow |
| `StatusBadge` | Renders `ReadinessStatus` via `STATUS_STYLES`; **the label is text**, not colour alone |
| `ReadinessBar` | `aria-hidden`, explicitly decorative — "the numeric score is always shown beside it". Width clamped `0–100`. |
| `EmptyState` | Title, optional hint, optional action — the canonical "nothing here yet" |
| `Modal` | `role="dialog"`, `aria-modal="true"`, Escape to close, focuses the panel on open, backdrop is a real `<button aria-label="Close dialog">` |
| `useToast()` | Self-dismissing after 3.5s inside a permanent `aria-live="polite"` region — "never a banner" |

`ReadinessStatus` is the union `"on_track" | "needs_attention" | "at_risk"`, with
`STATUS_STYLES` and `BAR_FILLS` as its lookup maps. This is the product's status vocabulary
and it is defined once.

### Measured contrast

Computed from the Avora token values using the WCAG 2.x formula. Every text and status token
clears 4.5:1 on **all three** surfaces (parchment / cream / linen); the worst case is the real
case, so the table below reports the lowest of the three.

**Text — lowest ratio across `canvas` / `surface` / `surface-muted`:**

| Token | Min ratio | Verdict |
|---|---|---|
| `ink-900` (`#2c1a0e`) | 14.02 | Passes AA and AAA |
| `ink-700` (`#4a3527`) | 9.66 | Passes AA and AAA |
| `ink-500` (`#786351`) | 4.77 | Passes AA (the dimmest token that may carry text) |
| `brand-600` (`#a85033`) | 4.58 | Passes AA — accent text and filled-button label |
| `brand-700` (`#96452a`) | 5.56 | Passes AA — accent hover/pressed and strong borders |
| `ok-700` / `warn-700` / `risk-600` | 6.91 / 6.35 / 6.41 | All pass AA |
| `remark-600` (`#5c438c`) | 6.70 | Passes AA |

A status badge renders its foreground on its own `-100` tint, not on the bare surface, and a 14%
tint darkens the background enough to pull an otherwise-passing token below 4.5:1 (`warn-700` on
the `warn-100` tint over linen was ~4.14 before the foregrounds were deepened). The four status
foregrounds are therefore set dark enough to clear 4.5:1 **over their tint on every surface**
(worst case ~5.2), and `contrast.test.ts` composites the tint and checks that composite, not just
the bare surface.

> **A fourth text step used to sit here.** `--color-ink-400` measured below 4.5:1 on every
> surface while all its uses were 11–14px copy. It could not be retuned: on a warm-paper palette
> the darkest value clearing 4.5:1 against `surface-muted` is `ink-500` itself, so a fourth muted
> step can only exist by being illegible. The token was removed and its uses moved to `ink-500`.
> `src/test/contrast.test.ts` fails if the name comes back.

**Non-text contrast (WCAG 1.4.11 requires 3:1 for component boundaries and state
indicators):**

| Pair | Ratio | Verdict |
|---|---|---|
| `line-control` on `surface` | 3.94 | Passes — this is the input border |
| `line-control` on `canvas` | 3.86 | Passes |
| `line-control` on `surface-muted` | 3.47 | Passes |
| `line` on `surface` | 1.33 | Decorative only — dividers and card edges, where WCAG sets no ratio |
| `line` on `canvas` | 1.31 | Decorative only |
| `line-strong` on `canvas` | 1.74 | Decorative only |
| `surface` vs `canvas` | 1.02 | Card edges are carried by the border, not the fill |

Filled buttons are fine: parchment (`canvas`) text on `brand-600` is 5.09, and on `risk-600`
is 7.1.

The hairlines are deliberately below 3:1 — a divider is not a control, and dimming is the
correct behaviour for one. `line-control` is the token for a real control boundary.

These numbers are not maintained by hand. `frontend/src/test/contrast.test.ts` parses the
tokens out of `index.css` and recomputes every ratio on each run, so a palette change that
breaks `UX-8` or `UX-9` fails the build rather than this table going quietly stale.

### Accessibility as practiced

Applied deliberately in a handful of files and largely absent elsewhere. Counted across
`frontend/src/**/*.tsx`:

**What is genuinely good:**

- **Decorative icons are hidden consistently** — ~30 `aria-hidden` across 17 files, on lucide
  icons, SVG marks, avatars, and `ReadinessBar`.
- **Icon-only buttons carry `aria-label`** — `AppShell` (×2), `ActivityMenu`,
  `DashboardHeader` (×3), `GroupLayout`.
- **Navigation landmarks are labelled** — both `<nav>` elements in `AppShell.tsx` carry
  `aria-label={`${title} navigation`}`; layout uses `<aside>`, `<header>`, `<main>`.
- **Toggle state is exposed** — `aria-expanded` on disclosure and menu triggers,
  `aria-pressed` on filter toggles in `ReadinessTable` and `StudentsTab`.
- **Status is never colour alone** — `StatusBadge` always renders its label as text.
- **The dialog is not a div** — `Modal` uses `role="dialog"`, `aria-modal="true"`,
  `aria-labelledby`, and its backdrop is a real `<button>`.
- **Semantics are used** — 85 `<button>`, 36 `<label>`, 18 `<form>`, 20 `<th>`, 9 `<section>`,
  4 `<nav>`, 3 `<header>`, 2 `<main>`, 2 `<aside>`. `index.html` sets `lang="en"` and a
  viewport meta.

**What is missing or wrong:**

- **`Modal` has no focus trap.** Tab moves out of the dialog to the page behind it.
- **`Modal` does not restore focus** to the trigger on close.
- **`Modal`'s `aria-labelledby` is the hardcoded id `manara-modal-title`.** Two simultaneous
  modals produce duplicate ids and an ambiguous accessible name.
- **`TutorChatPage.tsx` uses `role="assistant"`**, which is not a valid ARIA role and is
  ignored by assistive technology.
- **The streaming chat transcript has no `aria-live`**, so arriving AI text is silent.
- **There is no skip link** to bypass navigation.
- **Loading and error states are unannounced plain `<div>`s** — `"Loading…"` in `App.tsx:65`
  and `ProtectedRoute.tsx:21`.
- **There are zero `<fieldset>` elements**, so radio and checkbox groups have no group label.

---

## Standards

### Design system

**`UX-1` — MUST NOT · Critical · Active**
Do not wrap the retarget block in `frontend/src/index.css` (lines 44–283) in an `@layer`, and
do not remove it while stock Tailwind palette classes remain in the codebase.
*Rationale:* it wins the cascade only by being unlayered; layering it reverts the entire
application to stock Tailwind colours.

**`UX-2` — MUST · Important · Active**
New code uses semantic token classes — `bg-surface`, `text-ink-700`, `border-line`,
`bg-brand-600` — never stock Tailwind palette classes such as `bg-white`, `text-slate-600`,
or `bg-blue-600`.
*Rationale:* the stock names are silently redirected and mean something other than they say;
every new use deepens the two-vocabulary problem.

**`UX-3` — MUST · Important · Active**
Colours come from tokens. No hex literal appears in a component.
*Rationale:* a literal cannot be re-themed and will not have been contrast-checked.

**`UX-4` — MUST NOT · Important · Active**
Do not introduce a second accent colour. Terracotta is the only accent; `ok`, `warn`, `risk`
and `remark` are semantic — `remark` being a student's request-to-re-check, not a caution — used
only for their meanings, and are held apart in hue from the accent so the brand colour is never
mistaken for a status.
*Rationale:* an accent that means several things means nothing, and status colour is doing
real work in this product.

**`UX-5` — SHOULD · Recommended · Active**
Depth comes from surface lift and a 1px shadow, per `SectionCard`. Avoid glows and heavy
elevation.
*Rationale:* §02 P3 — the product is deliberately calm.

**`UX-6` — MUST · Important · Active**
Reuse the primitives in `components/ui.tsx`. A new generic primitive is added there, taking
its data via props.
*Rationale:* a second card or badge implementation is a second place accessibility behaviour
must be fixed.

### Accessibility

**`UX-7` — MUST · Critical · Active**
The product targets **WCAG 2.2 Level AA**. New interface work meets it; existing work is
brought up when touched.
*Rationale:* the users are children, some with access needs, and the tutor context is often
a school. This is the baseline, stated once.

**`UX-8` — MUST · Critical · Active**
Text meets 4.5:1 against its actual background; large text (≥18.66px bold or ≥24px) meets
3:1. **`ink-500` is the dimmest token that may carry normal text** — 5.31 / 5.41 / 4.77 across
the three surfaces. `brand-500` (sienna) is a soft/decorative accent and MUST NOT carry normal
text, where it measures ~2.4 on parchment.
*Rationale:* measured; see [Measured contrast](#measured-contrast). The rule previously named
`--color-ink-400` as forbidden for body text; that token no longer exists, which is the
stronger form of the same rule. Enforced by `frontend/src/test/contrast.test.ts`.

**`UX-9` — MUST · Critical · Active**
Interactive component boundaries and state indicators meet 3:1 against their background.
**`--color-line-control` is the token for that job** (3.94 on surface, 3.86 on canvas, 3.47 on
surface-muted). `--color-line` (1.33) and `--color-line-strong` (1.74) are decorative
hairlines — dividers, card edges, table rules — and MUST NOT be the sole visual boundary of an
interactive control.
*Rationale:* WCAG 1.4.11. A field whose edge is invisible is a field a low-vision user cannot
find. The rule previously pointed at `line-strong` as the remedy, which also fails 3:1;
`line-control` was added because nothing in the palette met the bar. Enforced by
`frontend/src/test/contrast.test.ts`, which also asserts the hairlines stay quiet, so their
low ratios read as a decision rather than an oversight.

**`UX-10` — MUST · Critical · Active**
Every interactive element has a visible focus indicator meeting 3:1 against adjacent colours.
The mechanism is a single unlayered `:focus-visible` rule in `index.css` that draws a 2px
terracotta (`brand-600`, ≥3:1 on parchment) outline on links, buttons, and form controls; it is
an **outline**, not a border colour, so it sidesteps the retarget cascade, and being unlayered it
wins even where a component set `focus:outline-none`. A component may still opt into a custom
indicator, but the default is now compliant rather than absent.
*Rationale:* keyboard operation is impossible without it, and the browser default ring is
unreliable against the parchment canvas (`#faf7f2`). A per-page focus ring was the old approach
and left most controls uncovered.

**`UX-11` — MUST · Critical · Active**
Every function is reachable and operable by keyboard alone, in a logical order. Dialogs trap
focus while open and restore it to the trigger on close.
*Rationale:* WCAG 2.1.1 and 2.4.3. `Modal` does neither today — see Known Gaps.

**`UX-12` — MUST · Important · Active**
Every form control has a programmatically associated label. Grouped controls use `<fieldset>`
and `<legend>`. Validation errors are associated with their control via `aria-describedby`
and announced.
*Rationale:* a placeholder is not a label, and an error shown only in colour or position is
invisible to a screen reader.

**`UX-13` — MUST · Important · Active**
Content that changes without a navigation — streaming AI output, async status transitions,
toasts, validation summaries — is announced through a live region. Use `aria-live="polite"`;
reserve `assertive` for errors that block progress.
*Rationale:* the chat transcript and the readiness "updating" state are currently silent.

**`UX-14` — MUST · Important · Active**
Decorative graphics are `aria-hidden`; meaningful graphics carry a text alternative. A
progress bar that duplicates an adjacent number is decorative.
*Rationale:* already the practice — `ReadinessBar` and `InitialsAvatar` do exactly this.
Stated so it survives.

**`UX-15` — MUST NOT · Important · Active**
Colour is never the sole carrier of meaning. Status is accompanied by text or an icon.
*Rationale:* WCAG 1.4.1. `StatusBadge` already renders its label; keep it.

**`UX-16` — MUST · Important · Active**
Use the semantic element for the job — `<button>` for actions, `<a>` for navigation,
`<table>` with `<th>` for tabular data, landmarks for layout. An ARIA role is a last resort,
and must be a real ARIA role.
*Rationale:* `role="assistant"` in `TutorChatPage.tsx` is not one, and does nothing.

**`UX-17` — SHOULD · Important · Active**
Respect `prefers-reduced-motion`: suppress non-essential transitions and any animation that
moves across the viewport.
*Rationale:* WCAG 2.3.3, and vestibular disorders are common enough to matter at any scale.

**`UX-18` — SHOULD · Recommended · Active**
Interactive targets are at least 24×24 CSS pixels, or have equivalent spacing.
*Rationale:* WCAG 2.5.8. Students submit work from phones.

### Interaction and honesty

**`UX-19` — MUST · Critical · Active**
A missing measurement is rendered in words — "not enough data yet", "no data" — never as `0`,
`0%`, or an empty bar.
*Rationale:* the interface half of `PROD-2`. A fabricated zero tells a student they failed
something they never attempted.

**`UX-20` — MUST · Important · Active**
Self-declared data is labelled as self-declared wherever it is shown, including past-paper
`timed`, `time_taken_minutes` and `attempted_at`.
*Rationale:* the interface half of `PROD-8`; the platform cannot observe these and must not
imply it did.

**`UX-21` — MUST · Important · Active**
A stale value being recomputed is shown with an explicit "updating" state over the last known
value. Never present a stale value as current, and never blank it.
*Rationale:* `is_updating` exists precisely for this; blanking loses information the tutor
needs, and silence misrepresents it.

**`UX-22` — MUST · Important · Active**
AI-produced values are visually distinguished as proposals until accepted, and the tutor's
override affordance is always present.
*Rationale:* §01 P4 is only real if the interface makes the distinction visible.

**`UX-23` — MUST · Important · Active**
Every asynchronous surface handles four states explicitly: loading, empty, error, and
loaded. Empty uses `EmptyState`; error states say what failed and what to do next.
*Rationale:* an unhandled empty state is where a fabricated zero appears.

**`UX-24` — MUST · Important · Active**
Destructive and irreversible actions require confirmation naming the specific object, and the
confirming control is labelled with the action rather than "OK".
*Rationale:* deletes are hard in this system — there are no soft deletes
(`governance/non-goals.md`).

**`UX-25` — SHOULD · Recommended · Active**
Error messages state what happened and the next action, in the reader's register: plain
language for parents and students, precise vocabulary for tutors.
*Rationale:* three audiences share one product; a message tuned for none of them serves none.

**`UX-26` — MUST · Important · Active**
Student-facing surfaces preserve the anti-cheating framing: the assistant explains and
guides, it does not supply answers to assigned work.
*Rationale:* a study aid that completes homework destroys the evidence readiness is computed
from — it corrupts the data, not just the ethics.

**`UX-27` — MUST · Important · Active**
A primary surface opens with a single sentence, in plain language, that answers the question
the surface exists to answer.
*Rationale:* a reader who stops after one line must still have a true answer, or the surface
is asking them to do the analysis themselves.
*Realised by:* `verdictLine1` (tutor home), `dueVerdict` (student home), `parentVerdict`
(parent screen).

**`UX-28` — MUST NOT · Important · Active**
No surface, style or constant may contain a literal grade or percentage threshold; a
readiness band is the position of the grade within the subject's ordered grade boundaries.
*Rationale:* subjects use different scales — `Subject.grade_scale` already carries which —
and a hardcoded `70` or `B` is wrong for every subject that does not share it.
*Realised by:* `services/grades.py:grade_band`, whose cut-offs are indices. The one surviving
score threshold is `statusOf` in `frontend/src/lib/readiness.ts`, private to the legacy
analytics table and marked as such.

**`UX-29` — MUST · Important · Active**
A section with nothing to report is not rendered; the surface's terminal state is a sentence.
*Rationale:* `UX-19` forbids a fabricated zero in a value; the same reasoning applies to a
panel, and an empty panel is indistinguishable from a failed load.

**`UX-30` — MUST NOT · Recommended · Active**
The tutor's home surface does not name an individual student **except where naming one is
necessary to communicate something actionable**, and never in a ranked or enumerated list.
*Rationale:* a surface designed to be opened many times a day must not be able to ambush its
reader with a named child they did not ask about. The narrowing is D3: a class narrative that
may never name anyone cannot say the one thing a tutor most needs to read — that a particular
learner has moved — so naming is permitted where it carries an action, and forbidden where it
would produce a league table. Encoded in the `class_brief` prompt
(`services/prompts.py`), not only in review.

**`UX-31` — MUST · Recommended · Active**
A readiness value shown to a student is shown with its direction of travel.
*Rationale:* a score with direction describes a situation that can be acted on; a score alone
reads as a standing judgement of the person.
*Realised by:* `DirectionMark` in `components/ui.tsx`, which renders nothing at all when the
direction is `null` — one point is not a trend, and `→` would claim a movement nothing
measured.

**`UX-32` (revised) — MUST NOT · Important · Active**
A student is never shown another student's score, grade, delta or identity. A student may be
shown **their own position** within an improvement ranking, on a surface dedicated to it,
never on a home surface, and never as a bare bottom placing.
*Rationale unchanged in substance:* the harm the original rule was written against is a
standing whose disappearance becomes the message, and a board that publishes classmates to
each other. Neither survives in the shipped design — the ranking exists and the ranked do not
appear. The original wording ("peer comparison … never as a persistent standing or rank")
would have forbidden the Improvement tab outright; `GOV-3` allows three responses to a rule a
change breaks, and this takes the second: the rule is superseded rather than quietly broken.
The de-anonymisation analysis this rests on, and the three residual risks accepted rather than
solved, are in `backend/app/services/improvement.py`.

**`UX-33` — MUST · Important · Active**
Generated narrative is present when the surface opens; no primary surface waits on a model
call to render its primary content.
*Rationale:* a surface whose value is that opening it is cheap cannot contain a model call in
its render path.
*Realised by:* `services/narrative.py` writing the paragraph from a background job, and
`api/narrative.py` serving a seek rather than a generation.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **`Modal` has no focus trap and no focus restore** (`components/ui.tsx:120–157`). | Breaks `UX-11`. Keyboard and screen-reader users tab out of the dialog into the page behind it and lose their place on close. | `blocking` |
| **Contrast is guarded at the token level, not at the point of use.** `contrast.test.ts` proves every token clears the ratio its role needs; nothing checks that a given token is used in the role it was measured for. | A `brand-500` (sienna) label used as body text (~2.4:1) would pass every test and still fail AA. The guard closes the systemic failure, not the individual mistake. | `before scale` |
| **`--color-line` (1.33 on surface) is the default border for many legacy inputs.** | Breaks `UX-9`. Form fields styled with a bare `border` have no perceptible boundary for low-vision users; the bare `input` element and token-based fields correctly use `line-control`. | `blocking` |
| **`role="assistant"` in `TutorChatPage.tsx`** is not a valid ARIA role. | Breaks `UX-16`. Silently does nothing; the author presumably believed it conveyed something. | `blocking` |
| **`Modal`'s panel carries `outline-none`** without a custom indicator. | Narrows `UX-10` for that one container. A global unlayered `:focus-visible` outline (terracotta, ≥3:1) now covers every interactive element, so this is the remaining exception, not the rule. | `nice to have` |
| **The streaming chat transcript has no `aria-live`.** | Breaks `UX-13`. Arriving AI text is silent to a screen reader — the primary content of that page. | `before scale` |
| **No skip link.** | Every page begins by tabbing through the full navigation. | `before scale` |
| **`Modal`'s `aria-labelledby` is a hardcoded id.** | Duplicate ids and an ambiguous accessible name if two modals are ever open. Latent, not yet triggered. | `nice to have` |
| **Loading and error states are unannounced `<div>`s** (`App.tsx:65`, `ProtectedRoute.tsx:21`). | Breaks `UX-13` at the application's entry point. | `before scale` |
| **Zero `<fieldset>` elements.** | Breaks `UX-12` for any grouped control. | `before scale` |
| **Two class vocabularies coexist** — semantic tokens and remapped stock Tailwind names. | `UX-2` stops it growing; converging the existing uses is unscheduled work, and until then the CSS cannot be simplified. | `before scale` |
| **No automated accessibility testing.** No axe, no lint rule, nothing in the (nonexistent) CI. | Every rule in this section is enforced by review alone. See `RISK-2`. | `blocking` |

Every item here is a code change and needs its own pull request. None is fixed by this
document.

---

## Review Triggers

Update this document when:

- A token is added, removed, or changed in `index.css` — including any change to the
  retarget layer.
- A primitive is added to or changed in `components/ui.tsx`.
- The CSP's `font-src` or `style-src` changes, which changes what typography is possible.
- A WCAG target version is adopted beyond 2.2 AA.
- An accessibility gap above is closed.
- Automated accessibility checking is introduced.
- A new user role or audience gains its own surfaces.
