# 02. UX & Accessibility Standards

> **Volume 1 — Product & UX** · Engineering Constitution v1.0 · Status: Active
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

- **No light mode.** `:root { color-scheme: dark }` and the palette is built for a dark
  canvas. Supporting both would double every contrast decision for a product whose users have
  not asked for it.
- **No component library.** No Radix, no shadcn, no Headless UI. Primitives are hand-rolled
  in `components/ui.tsx`. This is a deliberate cost: the project owns its accessibility
  behaviour rather than inheriting it, which is why the `Modal` gaps below are ours to fix.
- **No webfonts.** The CSP blocks external font hosts, so `--font-display` is a system serif
  stack. This is a security constraint expressed as a design constraint, not an oversight.
- **No second accent colour.** Beacon amber is the product's only accent. Status colours are
  semantic, not decorative.
- **No animation library.** Motion is CSS transitions where it clarifies a state change.

## Sources

Written from: `frontend/src/index.css` (283 lines); `frontend/src/components/ui.tsx`;
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

1. **Lines 3–42, the `@theme` block.** Design tokens as CSS custom properties. Tailwind
   generates utility classes from these: `bg-canvas`, `text-ink-500`, `border-line`,
   `bg-brand-600`, `font-display`.
2. **Lines 44–283, the retarget layer.** Unlayered CSS that redefines Tailwind's *stock*
   palette utilities — `.bg-white`, `.text-slate-500`, `.bg-blue-600` — to point at MANARA
   tokens.

### Colour tokens

| Group | Token | Value | Role |
|---|---|---|---|
| Surfaces | `--color-canvas` | `#0c1022` | "Midnight" — body, nav, hero |
| | `--color-surface` | `#1c2543` | "Slate" — cards, panels, modals |
| | `--color-surface-muted` | `#242e52` | Raised rows, hovers, skeletons |
| Text | `--color-ink-900` | `#f1ebe0` | "Parchment" — headings, primary text |
| | `--color-ink-700` | `#d7d3c8` | Body copy |
| | `--color-ink-500` | `#8a9bbe` | "Horizon" — labels, captions, nav |
| | `--color-ink-400` | `#66739a` | Muted meta, placeholders |
| Accent | `--color-brand-700/600/500` | `#a98844` / `#c9a55a` / `#d4b476` | "Beacon" — the product's only accent |
| | `--color-brand-100/50` | amber at 16% / 8% | Accent tints |
| Status | `--color-ok-700` / `ok-100` | `#7fc79a` | On track |
| | `--color-warn-700` / `warn-100` | `#dba14e` | Needs attention |
| | `--color-risk-600` / `risk-100` | `#d98a80` | At risk |
| Hairlines | `--color-line` | `#28325a` | Default borders, dividers |
| | `--color-line-strong` | `#394472` | Emphasised borders, scrollbar thumb |

`--color-gold-600/500/100` are aliases of the brand ramp, kept so older class names stay
valid. They are not a separate colour.

### The Tailwind retarget layer

**This is the mechanism that will surprise you.** Roughly 240 lines redefine Tailwind's stock
utilities:

```css
.bg-white       { background-color: var(--color-surface); color: var(--color-ink-700); }
.text-slate-500 { color: var(--color-ink-500); }
.bg-blue-600    { background-color: var(--color-brand-600); color: var(--color-canvas); }
.bg-green-100   { background-color: var(--color-ok-100); }
```

The comment at `index.css:44–53` explains why it works: **unlayered rules always win over
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

The layer also styles bare elements, which is why legacy inputs render correctly on dark:
`input, select, textarea` get `--color-canvas` background, `--color-ink-900` text, and
`--color-line` borders; placeholders get `--color-ink-400`.

### Typography

`--font-display` is `"Iowan Old Style", "Palatino Linotype", Palatino, Georgia, ui-serif,
serif` — **system fonts only, because the CSP blocks external font hosts**
(`frontend/vercel.json` sets `font-src 'self' data:`). The comment at `index.css:39–40` says
so explicitly. This is a security decision surfacing as a typographic one.

`h1` and `h2` use the display serif with `letter-spacing: -0.01em` and `--color-ink-900`.
`h3` stays sans — the comment notes that dense interface areas keep their clarity that way.
Everything below is the default sans stack.

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

Computed from the token values using the WCAG 2.x formula. **The palette is largely strong**;
two things fail.

**Text on `--color-canvas` (`#0c1022`):**

| Token | Ratio | Verdict |
|---|---|---|
| `ink-900` | 15.91 | Passes AA and AAA |
| `ink-700` | 12.62 | Passes AA and AAA |
| `ink-500` | 6.75 | Passes AA |
| `ink-400` | **4.03** | **Fails AA for normal text** (passes large text / UI) |
| `brand-600` | 8.10 | Passes AA |
| `ok-700` / `warn-700` / `risk-600` | 9.47 / 8.29 / 7.10 | All pass AA |

**Text on `--color-surface` (`#1c2543`):** `ink-900` 12.69, `ink-700` 10.06, `ink-500` 5.39,
`brand-700` 4.51 — all pass. **`ink-400` is 3.21 and fails AA for normal text.**

**Text on `--color-surface-muted` (`#242e52`):** **`ink-400` is 2.82 and fails every
threshold.** `brand-700` is 3.96 and fails AA for normal text.

**Non-text contrast (WCAG 1.4.11 requires 3:1 for component boundaries and state
indicators):**

| Pair | Ratio | Verdict |
|---|---|---|
| `line` on `surface` | **1.21** | **Fails** — this is the default input border |
| `line` on `canvas` | **1.52** | **Fails** |
| `line-strong` on `canvas` | **2.02** | **Fails** |
| `surface` vs `canvas` | 1.25 | Card edges are carried by the border and shadow, not the fill |

Filled buttons are fine: canvas text on `brand-600` is 8.10, and on `risk-600` is 7.10.

The conclusion is specific rather than general: **the palette is well-built, `ink-400` is
being used for text it cannot carry, and the hairline tokens are too quiet to serve as the
sole boundary of an interactive control.**

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
- **There is no focus-ring styling.** The application relies on the browser default against a
  dark canvas, and `Modal`'s panel carries `outline-none`.
- **Loading and error states are unannounced plain `<div>`s** — `"Loading…"` in `App.tsx:65`
  and `ProtectedRoute.tsx:21`.
- **There are zero `<fieldset>` elements**, so radio and checkbox groups have no group label.
- **No reduced-motion handling** — `prefers-reduced-motion` appears nowhere.

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
Do not introduce a second accent colour. Beacon amber is the only accent; `ok`, `warn` and
`risk` are semantic and used only for their meanings.
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
3:1. **`--color-ink-400` MUST NOT be used for body text on any surface** — it measures 4.03
on canvas, 3.21 on surface, and 2.82 on surface-muted.
*Rationale:* measured; see [Measured contrast](#measured-contrast). `ink-400` is usable only
for large text on canvas, and for genuinely decorative marks.

**`UX-9` — MUST · Critical · Active**
Interactive component boundaries and state indicators meet 3:1 against their background.
`--color-line` (1.21 on surface) MUST NOT be the sole visual boundary of an interactive
control; use `--color-line-strong` or a stronger token for input, select and textarea
borders.
*Rationale:* WCAG 1.4.11. A field whose edge is invisible is a field a low-vision user cannot
find.

**`UX-10` — MUST · Critical · Active**
Every interactive element has a visible focus indicator meeting 3:1 against adjacent colours.
`outline-none` is used only where a compliant custom indicator replaces it.
*Rationale:* keyboard operation is impossible without it, and the default ring is unreliable
against `#0c1022`.

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

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **`Modal` has no focus trap and no focus restore** (`components/ui.tsx:120–157`). | Breaks `UX-11`. Keyboard and screen-reader users tab out of the dialog into the page behind it and lose their place on close. | `blocking` |
| **`--color-ink-400` is used for body text and placeholders** but fails AA on every surface (4.03 / 3.21 / 2.82). | Breaks `UX-8` wherever it carries normal text — including `input::placeholder` at `index.css:133–136`. | `blocking` |
| **`--color-line` (1.21 on surface) is the default input border.** | Breaks `UX-9`. Form fields have no perceptible boundary for low-vision users. | `blocking` |
| **`role="assistant"` in `TutorChatPage.tsx`** is not a valid ARIA role. | Breaks `UX-16`. Silently does nothing; the author presumably believed it conveyed something. | `blocking` |
| **No focus-ring styling anywhere**, and `Modal`'s panel sets `outline-none`. | Breaks `UX-10`. The browser default is unreliable against `#0c1022`. | `blocking` |
| **The streaming chat transcript has no `aria-live`.** | Breaks `UX-13`. Arriving AI text is silent to a screen reader — the primary content of that page. | `before scale` |
| **No skip link.** | Every page begins by tabbing through the full navigation. | `before scale` |
| **`Modal`'s `aria-labelledby` is a hardcoded id.** | Duplicate ids and an ambiguous accessible name if two modals are ever open. Latent, not yet triggered. | `nice to have` |
| **Loading and error states are unannounced `<div>`s** (`App.tsx:65`, `ProtectedRoute.tsx:21`). | Breaks `UX-13` at the application's entry point. | `before scale` |
| **Zero `<fieldset>` elements.** | Breaks `UX-12` for any grouped control. | `before scale` |
| **No `prefers-reduced-motion` handling.** | Breaks `UX-17`. | `nice to have` |
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
