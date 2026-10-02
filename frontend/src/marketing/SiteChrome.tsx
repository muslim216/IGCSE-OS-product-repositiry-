import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { AvoraGrain, AvoraLockup } from "../components/brand";
import { buttonClasses } from "../components/controls";
import { useDocumentTitle } from "../components/page";
import { SITE } from "../lib/site";

/* The public site's header and footer. Shared by the landing page, the legal
   pages and anything else a signed-out visitor can reach, so the company looks
   like one company from every entry point. */

const NAV: { href: string; label: string }[] = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#students-and-parents", label: "Students & parents" },
  { href: "/#pricing", label: "Pricing" },
  { href: "/#faq", label: "FAQ" },
];

export function SiteHeader() {
  const [open, setOpen] = useState(false);
  return (
    <header className="sticky top-0 z-30 border-b border-line/70 bg-canvas/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-6 px-6">
        <Link to="/" aria-label="avora home">
          <AvoraLockup />
        </Link>
        <nav aria-label="Site" className="hidden items-center gap-7 text-sm md:flex">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-ink-700 transition-colors hover:text-ink-900"
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Link
            to="/login"
            className="hidden px-2 text-sm text-ink-700 transition-colors hover:text-ink-900 sm:inline"
          >
            Sign in
          </Link>
          <Link to="/signup" className={buttonClasses("primary", "sm", "hidden sm:inline-flex")}>
            Start as a tutor
          </Link>
          <button
            type="button"
            aria-expanded={open}
            aria-controls="site-menu"
            aria-label={open ? "Close menu" : "Open menu"}
            onClick={() => setOpen((v) => !v)}
            className="rounded-md p-2 text-ink-700 hover:bg-surface-muted md:hidden"
          >
            {open ? (
              <X aria-hidden className="h-5 w-5" />
            ) : (
              <Menu aria-hidden className="h-5 w-5" />
            )}
          </button>
        </div>
      </div>
      {open && (
        <nav
          id="site-menu"
          aria-label="Site"
          className="border-t border-line bg-canvas px-6 py-4 md:hidden"
        >
          <ul className="space-y-1">
            {NAV.map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className="block rounded-md px-2 py-2.5 text-ink-900 hover:bg-surface-muted"
                >
                  {item.label}
                </a>
              </li>
            ))}
            <li>
              <Link
                to="/login"
                className="block rounded-md px-2 py-2.5 text-ink-900 hover:bg-surface-muted"
              >
                Sign in
              </Link>
            </li>
          </ul>
          <Link to="/signup" className={buttonClasses("primary", "md", "mt-3 w-full")}>
            Start as a tutor
          </Link>
        </nav>
      )}
    </header>
  );
}

const FOOTER: { heading: string; links: { to: string; label: string }[] }[] = [
  {
    heading: "Product",
    links: [
      { to: "/#how-it-works", label: "How it works" },
      { to: "/#trust", label: "AI you can check" },
      { to: "/#pricing", label: "Pricing" },
      { to: "/#faq", label: "FAQ" },
    ],
  },
  {
    heading: "Get started",
    links: [
      { to: "/signup", label: "Start as a tutor" },
      { to: "/login", label: "Sign in" },
      { to: "/#students-and-parents", label: "Joining as a student or parent" },
    ],
  },
  {
    heading: "Legal",
    links: [{ to: "/privacy", label: "Privacy policy" }],
  },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-line bg-canvas">
      <div className="mx-auto grid max-w-6xl gap-10 px-6 py-14 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <AvoraLockup />
          <p className="mt-4 max-w-xs text-sm leading-relaxed text-ink-500">
            The operating system for IGCSE tutors — marking, readiness and reporting, with the tutor
            in charge.
          </p>
          {SITE.contactEmail && (
            <a
              href={`mailto:${SITE.contactEmail}`}
              className="mt-4 inline-block text-sm text-brand-600 hover:underline"
            >
              {SITE.contactEmail}
            </a>
          )}
        </div>
        {FOOTER.map((col) => (
          <div key={col.heading}>
            <p className="avora-label">{col.heading}</p>
            <ul className="mt-4 space-y-2.5 text-sm">
              {col.links.map((l) => (
                <li key={l.label}>
                  {l.to.startsWith("/#") ? (
                    <a href={l.to} className="text-ink-700 transition-colors hover:text-ink-900">
                      {l.label}
                    </a>
                  ) : (
                    <Link to={l.to} className="text-ink-700 transition-colors hover:text-ink-900">
                      {l.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-6 py-5 text-xs text-ink-500">
          <span>
            © {SITE.copyrightYear} {SITE.legalName}. All rights reserved.
          </span>
          <span>Built for IGCSE tutors, their students and their families.</span>
        </div>
      </div>
    </footer>
  );
}

/** A public page: header, content, footer, titled tab. */
export function PublicPage({ title, children }: { title: string; children: ReactNode }) {
  useDocumentTitle(title);
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <AvoraGrain />
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
