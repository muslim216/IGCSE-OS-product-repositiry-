/**
 * Public facts about avora the company, in one place, so the footer, legal
 * pages and contact links cannot drift apart.
 *
 * `contactEmail` is deliberately null until a real, monitored address exists:
 * a support link to an inbox nobody reads is worse than no link. Every surface
 * that would show it hides the link while it is null.
 */
export const SITE = {
  name: "avora",
  legalName: "avora",
  contactEmail: null as string | null,
  privacyEmail: null as string | null,
  copyrightYear: 2026,
} as const;
